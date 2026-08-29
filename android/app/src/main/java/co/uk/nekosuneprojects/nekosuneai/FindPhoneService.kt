package co.uk.nekosuneprojects.nekosuneai

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.media.AudioAttributes
import android.media.AudioManager
import android.media.Ringtone
import android.media.RingtoneManager
import android.os.IBinder
import androidx.core.app.NotificationCompat

class FindPhoneService : Service() {
    companion object {
        const val ACTION_START = "co.uk.nekosuneprojects.nekosuneai.FIND_START"
        const val ACTION_STOP = "co.uk.nekosuneprojects.nekosuneai.FIND_STOP"
    }

    private var ringtone: Ringtone? = null
    private var oldVolume: Int? = null

    override fun onCreate() {
        super.onCreate()
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel("find_phone", "Find my phone", NotificationManager.IMPORTANCE_HIGH))
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            stopRinging()
            stopSelf()
            return START_NOT_STICKY
        }
        startRinging()
        return START_STICKY
    }

    private fun startRinging() {
        val stopIntent = Intent(this, FindPhoneService::class.java).apply { action = ACTION_STOP }
        val stopPending = PendingIntent.getService(this, 7, stopIntent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        startForeground(1002, NotificationCompat.Builder(this, "find_phone")
            .setSmallIcon(android.R.drawable.ic_lock_idle_alarm)
            .setContentTitle("NekoSuneAI is finding this phone")
            .setContentText("Tap Stop when you find it")
            .setOngoing(true)
            .addAction(0, "STOP", stopPending)
            .build())

        if (ringtone?.isPlaying == true) return
        val audio = getSystemService(AudioManager::class.java)
        oldVolume = audio.getStreamVolume(AudioManager.STREAM_RING)
        audio.setStreamVolume(AudioManager.STREAM_RING, audio.getStreamMaxVolume(AudioManager.STREAM_RING), 0)
        val uri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE)
        ringtone = RingtoneManager.getRingtone(this, uri)?.apply {
            audioAttributes = AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_NOTIFICATION_RINGTONE).build()
            if (android.os.Build.VERSION.SDK_INT >= 28) isLooping = true
            play()
        }
    }

    private fun stopRinging() {
        ringtone?.stop()
        ringtone = null
        oldVolume?.let {
            try { getSystemService(AudioManager::class.java).setStreamVolume(AudioManager.STREAM_RING, it, 0) } catch (_: Exception) {}
        }
        oldVolume = null
    }

    override fun onDestroy() {
        stopRinging()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null
}
