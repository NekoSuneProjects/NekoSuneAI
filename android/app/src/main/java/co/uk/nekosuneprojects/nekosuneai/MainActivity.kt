package co.uk.nekosuneprojects.nekosuneai

import android.Manifest
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.speech.RecognizerIntent
import android.speech.tts.TextToSpeech
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import java.net.URLEncoder
import java.util.Locale
import kotlin.concurrent.thread

class MainActivity : AppCompatActivity(), TextToSpeech.OnInitListener {
    private lateinit var api: ApiClient
    private lateinit var prefs: android.content.SharedPreferences
    private lateinit var web: WebView
    private lateinit var chatInput: EditText
    private lateinit var replyView: TextView
    private var tts: TextToSpeech? = null

    private val askNotifications = registerForActivityResult(ActivityResultContracts.RequestPermission()) {}
    private val speechLauncher = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        if (result.resultCode == RESULT_OK) {
            val spoken = result.data?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)?.firstOrNull().orEmpty()
            if (spoken.isNotBlank()) { chatInput.setText(spoken); sendChat(spoken) }
        }
    }

    override fun onInit(status: Int) { if (status == TextToSpeech.SUCCESS) tts?.language = Locale.UK }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        api = ApiClient(this); prefs = getSharedPreferences("neko", MODE_PRIVATE); tts = TextToSpeech(this, this)

        val root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(32, 32, 32, 32) }
        val scroll = ScrollView(this).apply { addView(root) }
        root.addView(TextView(this).apply { text = "NekoSuneAI Android Companion"; textSize = 24f })
        root.addView(TextView(this).apply { text = "Talk to your Raspberry Pi assistant from anywhere you can securely reach it"; textSize = 14f })

        val server = EditText(this).apply { hint = "Pi URL, e.g. https://neko.example.com"; setText(prefs.getString("server_url", "")) }
        val token = EditText(this).apply { hint = "WEB_DASHBOARD_TOKEN"; setText(prefs.getString("token", "")) }
        root.addView(server); root.addView(token)

        root.addView(Button(this).apply {
            text = "Save + Connect"
            setOnClickListener {
                api.save(server.text.toString(), token.text.toString())
                ContextCompat.startForegroundService(this@MainActivity, Intent(this@MainActivity, CompanionService::class.java))
                if (Build.VERSION.SDK_INT >= 33) askNotifications.launch(Manifest.permission.POST_NOTIFICATIONS)
                loadAvatarFromPi()
            }
        })

        root.addView(TextView(this).apply { text = "Talk to Neko"; textSize = 20f; setPadding(0, 26, 0, 8) })
        replyView = TextView(this).apply { text = "Connect to the Pi, then type or use the microphone."; textSize = 15f; setPadding(0, 8, 0, 10) }
        root.addView(replyView)
        chatInput = EditText(this).apply { hint = "Ask NekoSuneAI anything…"; minLines = 2 }
        root.addView(chatInput)
        root.addView(Button(this).apply { text = "Send"; setOnClickListener { sendChat(chatInput.text.toString()) } })
        root.addView(Button(this).apply {
            text = "🎤 Talk to Neko"
            setOnClickListener {
                val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                    putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                    putExtra(RecognizerIntent.EXTRA_LANGUAGE, Locale.getDefault())
                    putExtra(RecognizerIntent.EXTRA_PROMPT, "Talk to NekoSuneAI")
                }
                speechLauncher.launch(intent)
            }
        })
        root.addView(Button(this).apply {
            text = "📷 Let Neko see through phone camera"
            setOnClickListener {
                if (!api.configured()) replyView.text = "Connect to the Pi first."
                else startActivity(Intent(this@MainActivity, CameraVisionActivity::class.java))
            }
        })
        root.addView(TextView(this).apply {
            text = "Camera vision is opt-in and foreground-only. The camera stops sharing as soon as you leave its preview screen."
            textSize = 11f
        })

        root.addView(TextView(this).apply { text = "VRM Avatar — loaded from your Pi"; textSize = 20f; setPadding(0, 26, 0, 8) })
        web = WebView(this).apply {
            layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 900)
            settings.javaScriptEnabled = true; settings.domStorageEnabled = true; webViewClient = WebViewClient()
        }
        root.addView(web)
        root.addView(Button(this).apply { text = "Reload avatar from Pi"; setOnClickListener { loadAvatarFromPi() } })

        root.addView(Button(this).apply { text = "Allow notification/SMS-style alerts"; setOnClickListener { startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS)) } })
        root.addView(Button(this).apply {
            text = "Test Find My Phone"
            setOnClickListener { ContextCompat.startForegroundService(this@MainActivity, Intent(this@MainActivity, FindPhoneService::class.java).apply { action = FindPhoneService.ACTION_START }) }
        })
        root.addView(Button(this).apply { text = "STOP ringing"; setOnClickListener { startService(Intent(this@MainActivity, FindPhoneService::class.java).apply { action = FindPhoneService.ACTION_STOP }) } })

        root.addView(TextView(this).apply {
            text = "The VRM renderer runs only while this screen is open. Background phone monitoring stays lightweight. For remote use away from home, connect through Tailscale/VPN or authenticated HTTPS instead of opening the raw Pi port."
            textSize = 12f; setPadding(0, 20, 0, 40)
        })
        setContentView(scroll)
        if (api.configured()) loadAvatarFromPi()
    }

    private fun loadAvatarFromPi() {
        if (!api.configured()) return
        thread(name = "NekoAvatarLoad") {
            val url = try { api.avatarUrl() } catch (_: Exception) { "" }
            runOnUiThread {
                if (url.isBlank()) replyView.text = "The Pi has no VRM configured yet. Set VRM_AVATAR_URL on the Pi."
                else web.loadUrl("file:///android_asset/avatar/index.html?model=" + URLEncoder.encode(url, "UTF-8"))
            }
        }
    }

    private fun sendChat(value: String) {
        val message = value.trim(); if (message.isBlank()) return
        replyView.text = "Neko is thinking…"
        web.evaluateJavascript("window.setNekoEmotion('neutral');window.setNekoGesture('idle');window.setNekoSpeaking(false);", null)
        thread(name = "NekoRemoteChat") {
            val answer = try { api.chat(message) } catch (e: Exception) { ChatReply("I couldn't reach the Pi: ${e.message}") }
            runOnUiThread {
                replyView.text = answer.text; chatInput.setText("")
                web.evaluateJavascript("window.setNekoEmotion('${safeJs(answer.emotion)}');window.setNekoGesture('${safeJs(answer.gesture)}');", null)
                animateTtsVisemes(answer.text)
                tts?.speak(answer.text, TextToSpeech.QUEUE_FLUSH, null, "neko-reply")
            }
        }
    }

    private fun animateTtsVisemes(text: String) {
        val vowels = text.lowercase().filter { it in "aeiouy" }.take(180)
        if (vowels.isEmpty()) return
        val duration = (text.length * 55L).coerceIn(1000L, 14000L)
        val step = (duration / vowels.length.coerceAtLeast(1)).coerceIn(55L, 150L)
        web.evaluateJavascript("window.setNekoSpeaking(true);", null)
        vowels.forEachIndexed { i, c ->
            val vis = when (c) { 'a' -> "aa"; 'e' -> "ee"; 'i','y' -> "ih"; 'o' -> "oh"; else -> "ou" }
            web.postDelayed({ web.evaluateJavascript("window.setNekoViseme('$vis',0.72);", null) }, i * step)
        }
        web.postDelayed({ web.evaluateJavascript("window.setNekoViseme('',0);window.setNekoSpeaking(false);window.setNekoGesture('idle');", null) }, duration)
    }

    private fun safeJs(value: String): String = value.replace("'", "").replace("\\", "").take(24)

    override fun onPause() { web.onPause(); super.onPause() }
    override fun onResume() { super.onResume(); web.onResume() }
    override fun onDestroy() { tts?.stop(); tts?.shutdown(); web.destroy(); super.onDestroy() }
}
