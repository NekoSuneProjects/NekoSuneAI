package co.uk.nekosuneprojects.nekosuneai

import android.Manifest
import android.content.Intent
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.speech.RecognizerIntent
import android.speech.tts.TextToSpeech
import android.text.InputType
import android.view.Gravity
import android.view.View
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
    private lateinit var discovery: DiscoveryManager
    private lateinit var web: WebView
    private lateinit var chatInput: EditText
    private lateinit var replyView: TextView
    private lateinit var connectionStatus: TextView
    private lateinit var serverInput: EditText
    private lateinit var tokenInput: EditText
    private lateinit var advancedBox: LinearLayout
    private var tts: TextToSpeech? = null
    @Volatile private var pairingBusy = false

    private val bg = Color.parseColor("#080914")
    private val surface = Color.parseColor("#111329")
    private val surface2 = Color.parseColor("#181B38")
    private val border = Color.parseColor("#292D55")
    private val text = Color.parseColor("#F4F2FF")
    private val muted = Color.parseColor("#B3B7DC")
    private val violet = Color.parseColor("#A78BFA")
    private val cyan = Color.parseColor("#67E8F9")

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
        window.statusBarColor = bg
        window.navigationBarColor = bg
        api = ApiClient(this)
        prefs = getSharedPreferences("neko", MODE_PRIVATE)
        discovery = DiscoveryManager(this)
        tts = TextToSpeech(this, this)

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(16), dp(18), dp(16), dp(40))
            setBackgroundColor(bg)
        }
        val scroll = ScrollView(this).apply { setBackgroundColor(bg); addView(root) }

        root.addView(LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            addView(TextView(this@MainActivity).apply {
                text = "N"
                gravity = Gravity.CENTER
                textSize = 22f
                setTextColor(bg)
                typeface = Typeface.DEFAULT_BOLD
                background = pill(violet, violet, 16f)
            }, LinearLayout.LayoutParams(dp(48), dp(48)))
            addView(LinearLayout(this@MainActivity).apply {
                orientation = LinearLayout.VERTICAL
                setPadding(dp(12), 0, 0, 0)
                addView(TextView(this@MainActivity).apply { text = "NekoSuneAI"; textSize = 22f; setTextColor(text); typeface = Typeface.DEFAULT_BOLD })
                addView(TextView(this@MainActivity).apply { text = "ANDROID COMPANION STUDIO"; textSize = 10f; setTextColor(violet); letterSpacing = .12f })
            })
        })

        connectionStatus = TextView(this).apply {
            setPadding(dp(12), dp(8), dp(12), dp(8))
            setTextColor(cyan)
            textSize = 12f
            background = pill(Color.parseColor("#17213A"), Color.parseColor("#345D77"), 14f)
            text = if (api.configured()) "● Connected to ${api.serverUrl}" else "● Not paired"
        }
        root.addView(connectionStatus, marginTop(16))

        root.addView(sectionTitle("Dashboard"), marginTop(18))
        val pairCard = card()
        pairCard.addView(kicker("QUICK CONNECT"))
        pairCard.addView(title("Pair this phone"))
        pairCard.addView(body("No URL or dashboard token needed. NekoSuneAI will find your Docker/Pi on this Wi-Fi, then you approve the phone from the Docker dashboard."))
        pairCard.addView(primaryButton("Discover & Pair", "⌁") { startDiscoveryAndPair() }, marginTop(12))
        pairCard.addView(secondaryButton("Advanced manual connection") {
            advancedBox.visibility = if (advancedBox.visibility == View.VISIBLE) View.GONE else View.VISIBLE
        }, marginTop(8))
        advancedBox = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            visibility = View.GONE
            setPadding(0, dp(10), 0, 0)
        }
        serverInput = field("Pi URL, e.g. https://neko.example.com", prefs.getString("server_url", "").orEmpty())
        tokenInput = field("WEB_DASHBOARD_TOKEN", prefs.getString("token", "").orEmpty()).apply {
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
        }
        advancedBox.addView(serverInput)
        advancedBox.addView(tokenInput, marginTop(8))
        advancedBox.addView(secondaryButton("Save manual connection") {
            api.save(serverInput.text.toString(), tokenInput.text.toString())
            onConnected()
        }, marginTop(8))
        pairCard.addView(advancedBox)
        root.addView(pairCard, marginTop(8))

        root.addView(sectionTitle("Chat"), marginTop(18))
        val chatCard = card()
        chatCard.addView(kicker("TALK TO NEKO"))
        replyView = body(if (api.configured()) "Ready. Ask me anything." else "Pair this phone with your Pi to start chatting.")
        chatCard.addView(replyView)
        chatInput = field("Ask NekoSuneAI anything…", "").apply { minLines = 2 }
        chatCard.addView(chatInput, marginTop(10))
        chatCard.addView(primaryButton("Send message", "➤") { sendChat(chatInput.text.toString()) }, marginTop(10))
        chatCard.addView(secondaryButton("🎤  Talk to Neko") {
            val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                putExtra(RecognizerIntent.EXTRA_LANGUAGE, Locale.getDefault())
                putExtra(RecognizerIntent.EXTRA_PROMPT, "Talk to NekoSuneAI")
            }
            speechLauncher.launch(intent)
        }, marginTop(8))
        root.addView(chatCard, marginTop(8))

        root.addView(sectionTitle("Vision & Avatar"), marginTop(18))
        val avatarCard = card()
        avatarCard.addView(kicker("LIVE COMPANION"))
        avatarCard.addView(title("VRM Avatar"))
        web = WebView(this).apply {
            layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(390))
            setBackgroundColor(Color.TRANSPARENT)
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            webViewClient = WebViewClient()
        }
        avatarCard.addView(web, marginTop(8))
        avatarCard.addView(primaryButton("📷  Let Neko see through phone camera") {
            if (!api.configured()) replyView.text = "Pair to the Pi first."
            else startActivity(Intent(this@MainActivity, CameraVisionActivity::class.java))
        }, marginTop(10))
        avatarCard.addView(secondaryButton("Reload avatar") { loadAvatarFromPi() }, marginTop(8))
        avatarCard.addView(body("Camera vision is opt-in and foreground-only. It stops sharing when you leave the camera preview."), marginTop(8))
        root.addView(avatarCard, marginTop(8))

        root.addView(sectionTitle("Phone Tools"), marginTop(18))
        val toolsCard = card()
        toolsCard.addView(secondaryButton("Allow notification / SMS-style alerts") { startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS)) })
        toolsCard.addView(secondaryButton("Test Find My Phone") {
            ContextCompat.startForegroundService(this@MainActivity, Intent(this@MainActivity, FindPhoneService::class.java).apply { action = FindPhoneService.ACTION_START })
        }, marginTop(8))
        toolsCard.addView(secondaryButton("Stop ringing") {
            startService(Intent(this@MainActivity, FindPhoneService::class.java).apply { action = FindPhoneService.ACTION_STOP })
        }, marginTop(8))
        root.addView(toolsCard, marginTop(8))

        root.addView(body("Remote access can still use Tailscale/VPN or authenticated HTTPS. Automatic pairing is intentionally local-network only by default."), marginTop(18))
        setContentView(scroll)
        if (api.configured()) onConnected(startService = false)
    }

    private fun startDiscoveryAndPair() {
        if (pairingBusy) return
        pairingBusy = true
        connectionStatus.text = "● Searching for NekoSuneAI on this Wi-Fi…"
        var requested = false
        discovery.discover(onFound = { url, name ->
            if (requested) return@discover
            requested = true
            discovery.stop()
            connectionStatus.post { connectionStatus.text = "● Found $name — sending approval request…" }
            thread(name = "NekoPairing") {
                try {
                    val pairing = api.requestPairing(url)
                    runOnUiThread { connectionStatus.text = "● Waiting for approval on Docker dashboard…" }
                    var result = PairingResult("pending")
                    repeat(75) {
                        if (result.connected || result.status == "rejected" || result.status == "expired") return@repeat
                        Thread.sleep(1600)
                        result = api.pollPairing(pairing)
                    }
                    runOnUiThread {
                        pairingBusy = false
                        when {
                            result.connected -> onConnected()
                            result.status == "rejected" -> connectionStatus.text = "● Pairing rejected on dashboard"
                            else -> connectionStatus.text = "● Pairing timed out — tap Discover & Pair to retry"
                        }
                    }
                } catch (e: Exception) {
                    runOnUiThread { pairingBusy = false; connectionStatus.text = "● Pairing failed: ${e.message}" }
                }
            }
        }, onStatus = { status -> connectionStatus.post { connectionStatus.text = "● $status" } })
    }

    private fun onConnected(startService: Boolean = true) {
        connectionStatus.text = "● Connected to ${api.serverUrl}"
        if (startService) ContextCompat.startForegroundService(this, Intent(this, CompanionService::class.java))
        if (Build.VERSION.SDK_INT >= 33) askNotifications.launch(Manifest.permission.POST_NOTIFICATIONS)
        loadAvatarFromPi()
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
        if (!api.configured()) { replyView.text = "Pair this phone with your Pi first."; return }
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

    private fun animateTtsVisemes(value: String) {
        val vowels = value.lowercase().filter { it in "aeiouy" }.take(180)
        if (vowels.isEmpty()) return
        val duration = (value.length * 55L).coerceIn(1000L, 14000L)
        val step = (duration / vowels.size.coerceAtLeast(1)).coerceIn(55L, 150L)
        web.evaluateJavascript("window.setNekoSpeaking(true);", null)
        vowels.forEachIndexed { i, c ->
            val vis = when (c) { 'a' -> "aa"; 'e' -> "ee"; 'i','y' -> "ih"; 'o' -> "oh"; else -> "ou" }
            web.postDelayed({ web.evaluateJavascript("window.setNekoViseme('$vis',0.72);", null) }, i * step)
        }
        web.postDelayed({ web.evaluateJavascript("window.setNekoViseme('',0);window.setNekoSpeaking(false);window.setNekoGesture('idle');", null) }, duration)
    }

    private fun card() = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(dp(16), dp(16), dp(16), dp(16))
        background = pill(surface, border, 16f)
    }
    private fun kicker(value: String) = TextView(this).apply { text = value; textSize = 10f; setTextColor(violet); typeface = Typeface.DEFAULT_BOLD; letterSpacing = .13f }
    private fun title(value: String) = TextView(this).apply { text = value; textSize = 19f; setTextColor(text); typeface = Typeface.DEFAULT_BOLD; setPadding(0, dp(4), 0, dp(5)) }
    private fun sectionTitle(value: String) = TextView(this).apply { text = value; textSize = 13f; setTextColor(muted); typeface = Typeface.DEFAULT_BOLD; letterSpacing = .06f }
    private fun body(value: String) = TextView(this).apply { text = value; textSize = 13f; setTextColor(muted); setLineSpacing(0f, 1.12f) }
    private fun field(hintText: String, value: String) = EditText(this).apply {
        hint = hintText; setText(value); setTextColor(text); setHintTextColor(Color.parseColor("#777DA9")); textSize = 14f
        setPadding(dp(12), dp(10), dp(12), dp(10)); background = pill(Color.parseColor("#0D0F24"), Color.parseColor("#343961"), 10f)
    }
    private fun primaryButton(label: String, icon: String = "", action: () -> Unit) = Button(this).apply {
        text = if (icon.isBlank()) label else "$icon  $label"; isAllCaps = false; textSize = 14f; setTextColor(Color.parseColor("#111329")); typeface = Typeface.DEFAULT_BOLD
        background = pill(violet, cyan, 12f); setOnClickListener { action() }
    }
    private fun secondaryButton(label: String, action: () -> Unit) = Button(this).apply {
        text = label; isAllCaps = false; textSize = 14f; setTextColor(text); background = pill(surface2, Color.parseColor("#3C4275"), 12f); setOnClickListener { action() }
    }
    private fun pill(fill: Int, stroke: Int, radius: Float) = GradientDrawable().apply { shape = GradientDrawable.RECTANGLE; setColor(fill); cornerRadius = dp(radius.toInt()).toFloat(); setStroke(dp(1), stroke) }
    private fun marginTop(top: Int) = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply { topMargin = dp(top) }
    private fun safeJs(value: String): String = value.replace("'", "").replace("\\", "").take(24)
    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()

    override fun onPause() { web.onPause(); super.onPause() }
    override fun onResume() { super.onResume(); web.onResume() }
    override fun onDestroy() { discovery.stop(); tts?.stop(); tts?.shutdown(); web.destroy(); super.onDestroy() }
}
