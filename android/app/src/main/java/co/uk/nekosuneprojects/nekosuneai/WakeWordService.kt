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
import android.speech.tts.TextToSpeech
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import java.util.Locale
import kotlin.concurrent.thread

class WakeWordService : Service(), RecognitionListener, TextToSpeech.OnInitListener {
    private enum class Mode { WAKE, COMMAND }

    private val handler = Handler(Looper.getMainLooper())
    private var recognizer: SpeechRecognizer? = null
    private var tts: TextToSpeech? = null
    private lateinit var api: ApiClient
    private var listening = false
    private var mode = Mode.WAKE
    private var lastWakeAt = 0L

    private val prefs by lazy { getSharedPreferences("neko", MODE_PRIVATE) }
    private val wakePhrase: String
        get() = prefs.getString("wake_phrase", DEFAULT_WAKE_PHRASE).orEmpty().trim().lowercase(Locale.getDefault()).ifBlank { DEFAULT_WAKE_PHRASE }

    override fun onCreate() {
        super.onCreate()
        api = ApiClient(this)
        tts = TextToSpeech(this, this)
        createChannel()
        startForeground(NOTIFICATION_ID, notification("Listening for “${wakePhrase}”"))
        if (!SpeechRecognizer.isRecognitionAvailable(this)) {
            updateNotification("Speech recognition is unavailable on this phone")
            stopSelf()
            return
        }
        recognizer = SpeechRecognizer.createSpeechRecognizer(this).also { it.setRecognitionListener(this) }
        mode = Mode.WAKE
        scheduleListen(250)
    }

    override fun onInit(status: Int) {
        if (status == TextToSpeech.SUCCESS) {
            tts?.language = Locale.getDefault()
            tts?.setSpeechRate(1.04f)
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            prefs.edit().putBoolean("wake_word_enabled", false).apply()
            stopSelf()
            return START_NOT_STICKY
        }
        prefs.edit().putBoolean("wake_word_enabled", true).apply()
        mode = Mode.WAKE
        scheduleListen(100)
        return START_STICKY
    }

    private fun startListening() {
        if (listening) return
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            updateNotification("Open NekoSuneAI once and allow microphone permission")
            stopSelf()
            return
        }
        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, Locale.getDefault())
            putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, mode == Mode.WAKE)
            putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 5)
            putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, true)
            if (mode == Mode.COMMAND) putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_COMPLETE_SILENCE_LENGTH_MILLIS, 900L)
        }
        try {
            listening = true
            recognizer?.startListening(intent)
            updateNotification(if (mode == Mode.WAKE) "Listening for “${wakePhrase}”" else "Listening — ask NekoSuneAI…")
        } catch (_: Exception) {
            listening = false
            scheduleListen(1200)
        }
    }

    private fun scheduleListen(delayMs: Long) {
        handler.removeCallbacksAndMessages(null)
        handler.postDelayed({ startListening() }, delayMs)
    }

    private fun inspectWake(results: android.os.Bundle?) {
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
        mode = Mode.COMMAND
        updateNotification("Hey Jarvis heard — listening for your request")
        scheduleListen(650)
    }

    private fun handleCommand(results: android.os.Bundle?) {
        val command = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull().orEmpty().trim()
        if (command.isBlank()) {
            returnToWake(600)
            return
        }
        updateNotification("You: ${command.take(60)}")
        if (!api.configured()) {
            speakAndReturn("Open NekoSuneAI and pair this phone to your server first.")
            return
        }
        thread(name = "NekoWakeChat") {
            val reply = try { api.chat(command).text } catch (e: Exception) { "I couldn't reach the NekoSuneAI server: ${e.message}" }
            handler.post {
                updateNotification("Neko: ${reply.take(70)}")
                speakAndReturn(reply)
            }
        }
    }

    private fun speakAndReturn(text: String) {
        listening = false
        try { recognizer?.cancel() } catch (_: Exception) {}
        tts?.speak(text, TextToSpeech.QUEUE_FLUSH, null, "neko-wake-reply")
        val wait = (text.length * 55L).coerceIn(1800L, 12000L)
        returnToWake(wait)
    }

    private fun returnToWake(delay: Long) {
        mode = Mode.WAKE
        scheduleListen(delay)
    }

    override fun onReadyForSpeech(params: android.os.Bundle?) {}
    override fun onBeginningOfSpeech() {}
    override fun onRmsChanged(rmsdB: Float) {}
    override fun onBufferReceived(buffer: ByteArray?) {}
    override fun onEndOfSpeech() { listening = false; scheduleListen(if (mode == Mode.WAKE) 550 else 300) }
    override fun onError(error: Int) {
        listening = false
        if (mode == Mode.COMMAND && error in setOf(SpeechRecognizer.ERROR_NO_MATCH, SpeechRecognizer.ERROR_SPEECH_TIMEOUT)) {
            returnToWake(700)
            return
        }
        val delay = when (error) {
            SpeechRecognizer.ERROR_RECOGNIZER_BUSY -> 1800L
            SpeechRecognizer.ERROR_TOO_MANY_REQUESTS -> 5000L
            SpeechRecognizer.ERROR_NETWORK, SpeechRecognizer.ERROR_NETWORK_TIMEOUT -> 2500L
            else -> 900L
        }
        scheduleListen(delay)
    }
    override fun onResults(results: android.os.Bundle?) {
        listening = false
        if (mode == Mode.WAKE) {
            inspectWake(results)
            if (mode == Mode.WAKE) scheduleListen(650)
        } else {
            handleCommand(results)
        }
    }
    override fun onPartialResults(partialResults: android.os.Bundle?) { if (mode == Mode.WAKE) inspectWake(partialResults) }
    override fun onEvent(eventType: Int, params: android.os.Bundle?) {}

    private fun createChannel() {
        if (Build.VERSION.SDK_INT >= 26) {
            val channel = NotificationChannel(CHANNEL_ID, "NekoSuneAI wake word", NotificationManager.IMPORTANCE_LOW).apply {
                description = "Keeps the optional Hey Jarvis listener active"
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
            .setContentTitle("NekoSuneAI · Hey Jarvis")
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
        tts?.stop()
        tts?.shutdown()
        tts = null
        listening = false
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    companion object {
        const val DEFAULT_WAKE_PHRASE = "hey jarvis"
        const val ACTION_STOP = "co.uk.nekosuneprojects.nekosuneai.WAKE_STOP"
        private const val CHANNEL_ID = "neko_wake_word"
        private const val NOTIFICATION_ID = 1842
    }
}
