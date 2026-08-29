package co.uk.nekosuneprojects.nekosuneai

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.PackageManager
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import org.json.JSONObject
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.concurrent.thread

class CompanionService : Service() {
    private val running = AtomicBoolean(false)
    private lateinit var api: ApiClient
    private val prefs by lazy { getSharedPreferences("neko", MODE_PRIVATE) }

    override fun onCreate() {
        super.onCreate()
        api = ApiClient(this)
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CHANNEL_ID, "NekoSuneAI Companion", NotificationManager.IMPORTANCE_LOW))
        refreshNotification()
        if (prefs.getBoolean("wake_word_enabled", false) && ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
            try { ContextCompat.startForegroundService(this, Intent(this, WakeWordService::class.java)) } catch (_: Exception) {}
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_TOGGLE_WAKE -> {
                val enabled = prefs.getBoolean("wake_word_enabled", false)
                if (enabled) {
                    prefs.edit().putBoolean("wake_word_enabled", false).apply()
                    stopService(Intent(this, WakeWordService::class.java))
                } else if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
                    prefs.edit().putBoolean("wake_word_enabled", true).apply()
                    ContextCompat.startForegroundService(this, Intent(this, WakeWordService::class.java))
                } else {
                    startActivity(Intent(this, WakeWordSettingsActivity::class.java).apply {
                        putExtra("enable_now", true)
                        addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    })
                }
                refreshNotification()
            }
        }
        if (running.compareAndSet(false, true)) {
            thread(name = "NekoCompanion", isDaemon = true) { loop() }
        }
        return START_STICKY
    }

    private fun refreshNotification() {
        val enabled = prefs.getBoolean("wake_word_enabled", false)
        val phrase = prefs.getString("wake_phrase", WakeWordService.DEFAULT_WAKE_PHRASE).orEmpty().ifBlank { WakeWordService.DEFAULT_WAKE_PHRASE }
        val open = PendingIntent.getActivity(
            this, 10, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val toggle = PendingIntent.getService(
            this, 11, Intent(this, CompanionService::class.java).setAction(ACTION_TOGGLE_WAKE),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val wakeSettings = PendingIntent.getActivity(
            this, 12, Intent(this, WakeWordSettingsActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val callSettings = PendingIntent.getActivity(
            this, 13, Intent(this, ScamCallSettingsActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        startForeground(NOTIFICATION_ID, NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle("NekoSuneAI connected")
            .setContentText(if (enabled) "Background wake ON · say “$phrase”" else "Low-power phone link active · background wake OFF")
            .setContentIntent(open)
            .setOngoing(true)
            .addAction(0, if (enabled) "Turn off wake" else "Enable Hey Jarvis", toggle)
            .addAction(0, "Wake settings", wakeSettings)
            .addAction(0, "Call protection", callSettings)
            .build())
    }

    private fun loop() {
        var lastId = 0
        var nextHeartbeat = 0L
        while (running.get()) {
            try {
                val now = System.currentTimeMillis()
                if (now >= nextHeartbeat) {
                    api.heartbeat()
                    nextHeartbeat = now + 5 * 60 * 1000L
                }
                for (cmd in api.longPoll(lastId)) {
                    lastId = maxOf(lastId, cmd.optInt("id", lastId))
                    handle(cmd)
                }
            } catch (_: Exception) {
                try { Thread.sleep(10_000) } catch (_: InterruptedException) { return }
            }
        }
    }

    private fun handle(cmd: JSONObject) {
        when (cmd.optString("command").uppercase()) {
            "FIND_PHONE", "RING" -> startForegroundService(Intent(this, FindPhoneService::class.java).apply {
                action = FindPhoneService.ACTION_START
            })
            "STOP_RING", "FOUND_PHONE" -> startService(Intent(this, FindPhoneService::class.java).apply {
                action = FindPhoneService.ACTION_STOP
            })
            "HEARTBEAT", "STATUS" -> try { api.heartbeat() } catch (_: Exception) {}
        }
    }

    override fun onDestroy() {
        running.set(false)
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    companion object {
        private const val CHANNEL_ID = "neko_companion"
        private const val NOTIFICATION_ID = 1001
        const val ACTION_TOGGLE_WAKE = "co.uk.nekosuneprojects.nekosuneai.TOGGLE_WAKE"
    }
}
