package co.uk.nekosuneprojects.nekosuneai

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import java.util.Locale

class WakeWordService : Service(), RecognitionListener {
    private val handler = Handler(Looper.getMainLooper())
    private var recognizer: SpeechRecognizer? = null
    private var listening = false
    private var lastWakeAt = 0L

    private val prefs by lazy { getSharedPreferences("neko", MODE_PRIVATE) }
    private val wakePhrase: String
        get() = prefs.getString("wake_phrase", DEFAULT_WAKE_PHRASE).orEmpty().trim().lowercase(Locale.getDefault()).ifBlank { DEFAULT_WAKE_PHRASE }

    override fun onCreate() {
        super.onCreate()
        createChannel()
        startForeground(NOTIFICATION_ID, notification("Listening for “${wakePhrase}”"))
        if (!SpeechRecognizer.isRecognitionAvailable(this)) {
            updateNotification("Speech recognition is unavailable on this phone")
            stopSelf()
            return
        }
        recognizer = SpeechRecognizer.createSpeechRecognizer(this).also { it.setRecognitionListener(this) }
        scheduleListen(250)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            prefs.edit().putBoolean("wake_word_enabled", false).apply()
            stopSelf()
            return START_NOT_STICKY
        }
        prefs.edit().putBoolean("wake_word_enabled", true).apply()
        scheduleListen(100)
        return START_STICKY
    }

    private fun startListening() {
        if (listening || ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
                updateNotification("Microphone permission is required")
                stopSelf()
            }
            return
        }
        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, Locale.getDefault())
            putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
            putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 5)
            putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, true)
        }
        try {
            listening = true
            recognizer?.startListening(intent)
            updateNotification("Listening for “${wakePhrase}”")
        } catch (_: Exception) {
            listening = false
            scheduleListen(1200)
        }
    }

    private fun scheduleListen(delayMs: Long) {
        handler.removeCallbacksAndMessages(null)
        handler.postDelayed({ startListening() }, delayMs)
    }

    private fun inspect(results: android.os.Bundle?) {
        val phrases = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION).orEmpty()
        if (phrases.any { normalized(it).contains(wakePhrase) }) triggerWake()
    }

    private fun normalized(value: String): String = value.lowercase(Locale.getDefault())
        .replace(Regex("[^a-z0-9 ]+"), " ")
        .replace(Regex("\\s+"), " ")
        .trim()

    private fun triggerWake() {
        val now = System.currentTimeMillis()
        if (now - lastWakeAt < 3500) return
        lastWakeAt = now
        listening = false
        try { recognizer?.cancel() } catch (_: Exception) {}
        updateNotification("Wake phrase heard — opening NekoSuneAI")
        val launch = Intent(this, MainActivity::class.java).apply {
            action = ACTION_WAKE_TRIGGERED
            putExtra(EXTRA_WAKE_TRIGGERED, true)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP)
        }
        startActivity(launch)
        scheduleListen(6000)
    }

    override fun onReadyForSpeech(params: android.os.Bundle?) {}
    override fun onBeginningOfSpeech() {}
    override fun onRmsChanged(rmsdB: Float) {}
    override fun onBufferReceived(buffer: ByteArray?) {}
    override fun onEndOfSpeech() { listening = false; scheduleListen(550) }
    override fun onError(error: Int) {
        listening = false
        val delay = when (error) {
            SpeechRecognizer.ERROR_RECOGNIZER_BUSY -> 1800L
            SpeechRecognizer.ERROR_TOO_MANY_REQUESTS -> 5000L
            SpeechRecognizer.ERROR_NETWORK, SpeechRecognizer.ERROR_NETWORK_TIMEOUT -> 2500L
            else -> 900L
        }
        scheduleListen(delay)
    }
    override fun onResults(results: android.os.Bundle?) { listening = false; inspect(results); scheduleListen(650) }
    override fun onPartialResults(partialResults: android.os.Bundle?) { inspect(partialResults) }
    override fun onEvent(eventType: Int, params: android.os.Bundle?) {}

    private fun createChannel() {
        if (Build.VERSION.SDK_INT >= 26) {
            val channel = NotificationChannel(CHANNEL_ID, "NekoSuneAI wake word", NotificationManager.IMPORTANCE_LOW).apply {
                description = "Keeps the optional local wake-word listener active"
                setSound(null, null)
            }
            getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
        }
    }

    private fun notification(message: String): Notification {
        val openIntent = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val stopIntent = PendingIntent.getService(
            this, 1, Intent(this, WakeWordService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle("NekoSuneAI background wake")
            .setContentText(message)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setContentIntent(openIntent)
            .addAction(0, "Turn off", stopIntent)
            .build()
    }

    private fun updateNotification(message: String) {
        getSystemService(NotificationManager::class.java).notify(NOTIFICATION_ID, notification(message))
    }

    override fun onDestroy() {
        handler.removeCallbacksAndMessages(null)
        try { recognizer?.cancel() } catch (_: Exception) {}
        try { recognizer?.destroy() } catch (_: Exception) {}
        recognizer = null
        listening = false
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    companion object {
        const val DEFAULT_WAKE_PHRASE = "hey jarvis"
        const val ACTION_STOP = "co.uk.nekosuneprojects.nekosuneai.WAKE_STOP"
        const val ACTION_WAKE_TRIGGERED = "co.uk.nekosuneprojects.nekosuneai.WAKE_TRIGGERED"
        const val EXTRA_WAKE_TRIGGERED = "wake_triggered"
        private const val CHANNEL_ID = "neko_wake_word"
        private const val NOTIFICATION_ID = 1842
    }
}
