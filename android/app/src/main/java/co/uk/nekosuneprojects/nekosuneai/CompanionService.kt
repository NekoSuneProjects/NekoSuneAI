package co.uk.nekosuneprojects.nekosuneai

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.os.IBinder
import androidx.core.app.NotificationCompat
import org.json.JSONObject
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.concurrent.thread

class CompanionService : Service() {
    private val running = AtomicBoolean(false)
    private lateinit var api: ApiClient

    override fun onCreate() {
        super.onCreate()
        api = ApiClient(this)
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel("neko_companion", "NekoSuneAI Companion", NotificationManager.IMPORTANCE_LOW))
        startForeground(1001, NotificationCompat.Builder(this, "neko_companion")
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle("NekoSuneAI connected")
            .setContentText("Low-power phone link is active")
            .setOngoing(true)
            .build())
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (running.compareAndSet(false, true)) {
            thread(name = "NekoCompanion", isDaemon = true) { loop() }
        }
        return START_STICKY
    }

    private fun loop() {
        var lastId = 0
        var nextHeartbeat = 0L
        while (running.get()) {
            try {
                val now = System.currentTimeMillis()
                if (now >= nextHeartbeat) {
                    api.heartbeat()
                    // Telemetry is deliberately slow; long-poll handles commands.
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
}
