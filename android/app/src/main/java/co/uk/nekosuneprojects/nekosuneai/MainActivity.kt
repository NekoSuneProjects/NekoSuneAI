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
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.splashscreen.SplashScreen.Companion.installSplashScreen
import java.net.URLEncoder
import java.util.Locale
import kotlin.concurrent.thread

class MainActivity : AppCompatActivity(), TextToSpeech.OnInitListener {
    private lateinit var api: ApiClient
    private lateinit var prefs: android.content.SharedPreferences
    private lateinit var discovery: DiscoveryManager
    private lateinit var contentHost: LinearLayout
    private lateinit var connectionStatus: TextView
    private lateinit var chatInput: EditText
    private lateinit var chatHistory: TextView
    private lateinit var web: WebView
    private lateinit var serverInput: EditText
    private lateinit var tokenInput: EditText
    private lateinit var discoveredBox: LinearLayout
    private var tts: TextToSpeech? = null
    @Volatile private var pairingBusy = false
    private val foundServers = linkedSetOf<String>()

    private val bg = Color.parseColor("#080914")
    private val surface = Color.parseColor("#111329")
    private val surface2 = Color.parseColor("#181B38")
    private val border = Color.parseColor("#292D55")
    private val textColor = Color.parseColor("#F4F2FF")
    private val muted = Color.parseColor("#B3B7DC")
    private val violet = Color.parseColor("#A78BFA")
    private val cyan = Color.parseColor("#67E8F9")

    private val askNotifications = registerForActivityResult(ActivityResultContracts.RequestPermission()) {}
    private val speechLauncher = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        if (result.resultCode == RESULT_OK) {
            val spoken = result.data?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)?.firstOrNull().orEmpty()
            if (spoken.isNotBlank()) sendChat(spoken)
        }
    }

    override fun onInit(status: Int) {
        if (status == TextToSpeech.SUCCESS) {
            tts?.language = Locale.getDefault()
            tts?.setSpeechRate(1.04f)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        val splash = installSplashScreen()
        super.onCreate(savedInstanceState)
        splash.setOnExitAnimationListener { provider ->
            provider.view.animate().alpha(0f).scaleX(1.08f).scaleY(1.08f).setDuration(320L).withEndAction { provider.remove() }.start()
        }
        window.statusBarColor = bg
        window.navigationBarColor = bg
        api = ApiClient(this)
        prefs = getSharedPreferences("neko", MODE_PRIVATE)
        discovery = DiscoveryManager(this)
        tts = TextToSpeech(this, this)

        val shell = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; setBackgroundColor(bg) }
        shell.addView(buildSidebar(), LinearLayout.LayoutParams(dp(92), LinearLayout.LayoutParams.MATCH_PARENT))
        contentHost = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setBackgroundColor(bg); setPadding(dp(14), dp(14), dp(14), dp(24)) }
        val scroll = ScrollView(this).apply { isFillViewport = true; setBackgroundColor(bg); addView(contentHost) }
        shell.addView(scroll, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.MATCH_PARENT, 1f))
        setContentView(shell)

        showCompanionPage()
        if (api.configured()) autoReconnect()
    }

    private fun buildSidebar(): View {
        val rail = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_HORIZONTAL
            setPadding(dp(7), dp(14), dp(7), dp(14))
            setBackgroundColor(Color.parseColor("#0B0D1D"))
        }
        rail.addView(ImageView(this).apply { setImageResource(R.drawable.ic_neko_logo); scaleType = ImageView.ScaleType.FIT_CENTER }, LinearLayout.LayoutParams(dp(46), dp(46)))
        rail.addView(navButton("Face", "◉") { showCompanionPage() }, marginTop(16))
        rail.addView(navButton("Chat", "✦") { showChatPage() }, marginTop(8))
        rail.addView(navButton("Music", "♫") { showMediaPage() }, marginTop(8))
        rail.addView(navButton("Vision", "⌾") { showVisionPage() }, marginTop(8))
        rail.addView(navButton("Remote", "⌁") { showRemotePage() }, marginTop(8))
        rail.addView(navButton("Pair", "⚙") { showConnectionPage() }, marginTop(8))
        return rail
    }

    private fun resetPage(title: String, subtitle: String) {
        contentHost.removeAllViews()
        contentHost.addView(TextView(this).apply { text = title; textSize = 23f; setTextColor(textColor); typeface = Typeface.DEFAULT_BOLD })
        contentHost.addView(TextView(this).apply { text = subtitle; textSize = 11f; setTextColor(muted); setPadding(0, dp(3), 0, dp(10)) })
        connectionStatus = TextView(this).apply {
            text = if (api.configured()) "● ${api.rememberedConnectionLabel()}" else "● Not paired"
            textSize = 11f; setTextColor(cyan); setPadding(dp(10), dp(7), dp(10), dp(7)); background = pill(Color.parseColor("#17213A"), Color.parseColor("#345D77"), 12f)
        }
        contentHost.addView(connectionStatus)
    }

    private fun showCompanionPage() {
        resetPage("NekoSuneAI", "Portable companion · the AI still runs on your Docker/Pi server")
        val card = card()
        card.addView(kicker("LIVE COMPANION"))
        card.addView(title("Face-to-face mode"))
        card.addView(body("Talk to the same NekoSuneAI profile from your phone. Your paired server, memory and model stay in charge."))
        web = WebView(this).apply {
            layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(470))
            setBackgroundColor(Color.TRANSPARENT)
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            webViewClient = WebViewClient()
        }
        card.addView(web, marginTop(10))
        card.addView(primaryButton("🎤 Talk to Neko") { launchSpeech() }, marginTop(10))
        card.addView(secondaryButton("Open text chat") { showChatPage() }, marginTop(8))
        contentHost.addView(card, marginTop(12))
        if (api.configured()) loadAvatarFromPi() else web.loadData("<html><body style='background:transparent;color:#b3b7dc;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100%'>Pair your phone to load the VRM.</body></html>", "text/html", "UTF-8")
    }

    private fun showChatPage() {
        resetPage("Chat", "Messages and spoken replies from the Docker-hosted AI")
        val card = card(); card.addView(kicker("CONVERSATION")); card.addView(title("Talk to Neko"))
        chatHistory = body("Neko: Ready. Ask me anything.").apply { setTextColor(textColor); minHeight = dp(160); setPadding(dp(12), dp(12), dp(12), dp(12)); background = pill(Color.parseColor("#0D0F24"), Color.parseColor("#343961"), 12f) }
        card.addView(chatHistory)
        chatInput = field("Message NekoSuneAI…", "").apply { minLines = 2; maxLines = 5 }
        card.addView(chatInput, marginTop(10))
        card.addView(primaryButton("Send", "➤") { sendChat(chatInput.text.toString()) }, marginTop(8))
        card.addView(secondaryButton("🎤 Voice message") { launchSpeech() }, marginTop(8))
        contentHost.addView(card, marginTop(12))
    }

    private fun showMediaPage() {
        resetPage("Music Remote", "Control YouTube Music running on your NekoSuneAI Docker host")
        val card = card(); card.addView(kicker("REMOTE MEDIA")); card.addView(title("YouTube Music")); card.addView(body("These controls send commands to the same AI/music player used by the Docker dashboard."))
        val search = field("Song, artist or YouTube query…", "")
        card.addView(search, marginTop(8))
        card.addView(primaryButton("Play on YouTube", "▶") { val q = search.text.toString().trim(); if (q.isNotBlank()) runRemoteCommand("play $q on youtube") }, marginTop(8))
        val row1 = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        row1.addView(smallButton("⏮", "previous song"), LinearLayout.LayoutParams(0, dp(48), 1f)); row1.addView(smallButton("⏸", "pause music"), LinearLayout.LayoutParams(0, dp(48), 1f)); row1.addView(smallButton("▶", "resume music"), LinearLayout.LayoutParams(0, dp(48), 1f)); row1.addView(smallButton("⏭", "next song"), LinearLayout.LayoutParams(0, dp(48), 1f))
        card.addView(row1, marginTop(10))
        val row2 = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        row2.addView(smallButton("−", "music volume 40"), LinearLayout.LayoutParams(0, dp(48), 1f)); row2.addView(smallButton("■", "stop music"), LinearLayout.LayoutParams(0, dp(48), 1f)); row2.addView(smallButton("+", "music volume 80"), LinearLayout.LayoutParams(0, dp(48), 1f))
        card.addView(row2, marginTop(8))
        card.addView(secondaryButton("What is playing?") { runRemoteCommand("music status") }, marginTop(8))
        card.addView(secondaryButton("Play a playlist") { val q = search.text.toString().trim(); if (q.isNotBlank()) runRemoteCommand("play my $q playlist") }, marginTop(8))
        contentHost.addView(card, marginTop(12))
    }

    private fun showVisionPage() {
        resetPage("Vision", "Let Neko see you through the phone camera and react to visible cues")
        val card = card(); card.addView(kicker("FRONT CAMERA")); card.addView(title("See & react")); card.addView(body("The camera screen sends occasional frames to your server. Visible facial-expression cues are treated as tentative, and the server can return a spoken check-in."))
        card.addView(primaryButton("📷 Start face vision") { if (api.configured()) startActivity(Intent(this, CameraVisionActivity::class.java)) else connectionStatus.text = "● Pair first" }, marginTop(10))
        card.addView(secondaryButton("Back to Face mode") { showCompanionPage() }, marginTop(8))
        contentHost.addView(card, marginTop(12))
    }

    private fun showRemotePage() {
        resetPage("Remote", "Phone tools and anywhere-access controls")
        val card = card(); card.addView(kicker("PHONE REMOTE")); card.addView(title("Portable controls"));
        card.addView(secondaryButton("Allow notification access") { startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS)) })
        card.addView(secondaryButton("Test Find My Phone") { ContextCompat.startForegroundService(this, Intent(this, FindPhoneService::class.java).apply { action = FindPhoneService.ACTION_START }) }, marginTop(8))
        card.addView(secondaryButton("Stop phone ringing") { startService(Intent(this, FindPhoneService::class.java).apply { action = FindPhoneService.ACTION_STOP }) }, marginTop(8))
        card.addView(primaryButton("🎤 Wake / voice command") { launchSpeech() }, marginTop(10))
        card.addView(body("For use away from home, set the remembered server URL to your authenticated HTTPS/VPN/Tailscale address. The saved paired token is reused automatically when the app opens."), marginTop(10))
        contentHost.addView(card, marginTop(12))
    }

    private fun showConnectionPage() {
        resetPage("Connection", "Pair once, remember the device, and reconnect automatically next time")
        val pairCard = card(); pairCard.addView(kicker("QUICK CONNECT")); pairCard.addView(title("Pair this phone")); pairCard.addView(body("Search this Wi-Fi, choose your NekoSuneAI server, then approve the request on the Docker dashboard."))
        pairCard.addView(primaryButton("Find NekoSuneAI servers", "⌁") { startDiscovery() }, marginTop(10))
        discoveredBox = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; visibility = View.GONE; setPadding(0, dp(10), 0, 0) }; pairCard.addView(discoveredBox)
        serverInput = field("Server URL", api.serverUrl)
        tokenInput = field("Dashboard token (manual only)", prefs.getString("token", "").orEmpty()).apply { inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD }
        pairCard.addView(serverInput, marginTop(12)); pairCard.addView(tokenInput, marginTop(8))
        pairCard.addView(secondaryButton("Save manual / remote URL") { api.save(serverInput.text.toString(), tokenInput.text.toString()); onConnected() }, marginTop(8))
        pairCard.addView(secondaryButton("Forget this device pairing") { api.clearConnection(); connectionStatus.text = "● Pairing forgotten" }, marginTop(8))
        contentHost.addView(pairCard, marginTop(12))
    }

    private fun launchSpeech() {
        speechLauncher.launch(Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, Locale.getDefault())
            putExtra(RecognizerIntent.EXTRA_PROMPT, "Talk to NekoSuneAI")
        })
    }

    private fun autoReconnect() {
        connectionStatus.text = "● Reconnecting to remembered server…"
        thread(name = "NekoAutoReconnect") {
            val ok = api.ping()
            runOnUiThread {
                if (ok) onConnected() else connectionStatus.text = "● Saved server offline — pairing is still remembered"
            }
        }
    }

    private fun startDiscovery() {
        if (pairingBusy) return
        foundServers.clear(); discoveredBox.removeAllViews(); discoveredBox.visibility = View.VISIBLE; discoveredBox.addView(body("Searching…")); connectionStatus.text = "● Searching this Wi-Fi…"
        discovery.discover(onFound = { url, name -> runOnUiThread { addDiscoveredServer(url, name) } }, onStatus = { s -> connectionStatus.post { connectionStatus.text = "● $s" } })
    }

    private fun addDiscoveredServer(url: String, name: String) {
        if (!foundServers.add(url)) return
        if (foundServers.size == 1) discoveredBox.removeAllViews()
        val c = card().apply { addView(title(name)); addView(body(url)); addView(primaryButton("Request pairing") { requestPairing(url, name) }, marginTop(8)) }
        discoveredBox.addView(c, if (foundServers.size == 1) LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT) else marginTop(8))
    }

    private fun requestPairing(url: String, name: String) {
        if (pairingBusy) return
        pairingBusy = true; discovery.stop(); connectionStatus.text = "● Pair request sent to $name…"
        thread(name = "NekoPairing") {
            try {
                val pairing = api.requestPairing(url); var result = PairingResult("pending"); var attempts = 0
                while (attempts < 75 && !result.connected && result.status !in setOf("rejected", "expired")) { Thread.sleep(1600); result = api.pollPairing(pairing); attempts++ }
                runOnUiThread { pairingBusy = false; if (result.connected) onConnected() else connectionStatus.text = "● Pairing ${result.status}" }
            } catch (e: Exception) { runOnUiThread { pairingBusy = false; connectionStatus.text = "● Pairing failed: ${e.message}" } }
        }
    }

    private fun onConnected(startService: Boolean = true) {
        discovery.stop(); connectionStatus.text = "● Connected · pairing saved"
        if (startService) ContextCompat.startForegroundService(this, Intent(this, CompanionService::class.java))
        if (Build.VERSION.SDK_INT >= 33) askNotifications.launch(Manifest.permission.POST_NOTIFICATIONS)
        if (::web.isInitialized) loadAvatarFromPi()
    }

    private fun loadAvatarFromPi() {
        if (!api.configured() || !::web.isInitialized) return
        thread(name = "NekoAvatarLoad") {
            val url = try { api.avatarUrl() } catch (_: Exception) { "" }
            runOnUiThread {
                if (url.isBlank()) {
                    web.loadData("<html><body style='background:transparent;color:#b3b7dc;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100%'>No VRM uploaded on the Docker server.</body></html>", "text/html", "UTF-8")
                } else {
                    web.loadUrl("file:///android_asset/avatar/index.html?model=" + URLEncoder.encode(url, "UTF-8"))
                }
            }
        }
    }

    private fun sendChat(value: String) {
        val message = value.trim(); if (message.isBlank()) return
        if (!api.configured()) { if (::chatHistory.isInitialized) chatHistory.text = "Pair this phone first."; return }
        if (!::chatHistory.isInitialized) showChatPage()
        chatHistory.append("\n\nYou: $message\nNeko: Thinking…")
        chatInput.setText("")
        thread(name = "NekoRemoteChat") {
            val answer = try { api.chat(message) } catch (e: Exception) { ChatReply("I couldn't reach the server: ${e.message}") }
            runOnUiThread {
                val old = chatHistory.text.toString().replace("Neko: Thinking…", "Neko: ${answer.text}")
                chatHistory.text = old
                if (::web.isInitialized) {
                    web.evaluateJavascript("window.setNekoEmotion('${safeJs(answer.emotion)}');window.setNekoGesture('${safeJs(answer.gesture)}');", null)
                    animateTtsVisemes(answer.text)
                }
                tts?.speak(answer.text, TextToSpeech.QUEUE_FLUSH, null, "neko-reply")
                connectionStatus.text = "● Ready"
            }
        }
    }

    private fun runRemoteCommand(command: String) {
        connectionStatus.text = "● Sending remote command…"
        thread(name = "NekoRemoteCommand") {
            val answer = try { api.musicCommand(command) } catch (e: Exception) { ChatReply("Remote command failed: ${e.message}") }
            runOnUiThread { connectionStatus.text = "● ${answer.text.take(72)}"; tts?.speak(answer.text, TextToSpeech.QUEUE_FLUSH, null, "neko-remote") }
        }
    }

    private fun animateTtsVisemes(value: String) {
        if (!::web.isInitialized) return
        val vowels = value.lowercase().filter { it in "aeiouy" }.take(180); if (vowels.isEmpty()) return
        val duration = (value.length * 55L).coerceIn(1000L, 14000L); val step = (duration / vowels.length.coerceAtLeast(1)).coerceIn(55L, 150L)
        web.evaluateJavascript("window.setNekoSpeaking(true);", null)
        vowels.forEachIndexed { i, c -> val vis = when (c) { 'a' -> "aa"; 'e' -> "ee"; 'i','y' -> "ih"; 'o' -> "oh"; else -> "ou" }; web.postDelayed({ web.evaluateJavascript("window.setNekoViseme('$vis',0.72);", null) }, i * step) }
        web.postDelayed({ web.evaluateJavascript("window.setNekoViseme('',0);window.setNekoSpeaking(false);window.setNekoGesture('idle');", null) }, duration)
    }

    private fun navButton(label: String, icon: String, action: () -> Unit) = Button(this).apply {
        text = "$icon\n$label"; isAllCaps = false; textSize = 10f; setTextColor(textColor); gravity = Gravity.CENTER; setPadding(2, 5, 2, 5); background = pill(surface2, border, 12f); setOnClickListener { action() }
    }
    private fun smallButton(label: String, command: String) = Button(this).apply { text = label; isAllCaps = false; textSize = 18f; setTextColor(textColor); background = pill(surface2, border, 10f); setOnClickListener { runRemoteCommand(command) } }
    private fun card() = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dp(14), dp(14), dp(14), dp(14)); background = pill(surface, border, 16f) }
    private fun kicker(value: String) = TextView(this).apply { text = value; textSize = 9f; setTextColor(violet); typeface = Typeface.DEFAULT_BOLD; letterSpacing = .12f }
    private fun title(value: String) = TextView(this).apply { text = value; textSize = 18f; setTextColor(textColor); typeface = Typeface.DEFAULT_BOLD; setPadding(0, dp(4), 0, dp(5)) }
    private fun body(value: String) = TextView(this).apply { text = value; textSize = 12f; setTextColor(muted); setLineSpacing(0f, 1.12f) }
    private fun field(hintText: String, value: String) = EditText(this).apply { hint = hintText; setText(value); setTextColor(textColor); setHintTextColor(Color.parseColor("#777DA9")); textSize = 13f; setPadding(dp(11), dp(10), dp(11), dp(10)); background = pill(Color.parseColor("#0D0F24"), Color.parseColor("#343961"), 10f) }
    private fun primaryButton(label: String, icon: String = "", action: () -> Unit) = Button(this).apply { text = if (icon.isBlank()) label else "$icon  $label"; isAllCaps = false; textSize = 13f; setTextColor(Color.parseColor("#111329")); typeface = Typeface.DEFAULT_BOLD; background = pill(violet, cyan, 12f); setOnClickListener { action() } }
    private fun secondaryButton(label: String, action: () -> Unit) = Button(this).apply { text = label; isAllCaps = false; textSize = 13f; setTextColor(textColor); background = pill(surface2, Color.parseColor("#3C4275"), 12f); setOnClickListener { action() } }
    private fun pill(fill: Int, stroke: Int, radius: Float) = GradientDrawable().apply { shape = GradientDrawable.RECTANGLE; setColor(fill); cornerRadius = dp(radius.toInt()).toFloat(); setStroke(dp(1), stroke) }
    private fun marginTop(top: Int) = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply { topMargin = dp(top) }
    private fun safeJs(value: String): String = value.replace("'", "").replace("\\", "").take(24)
    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()

    override fun onResume() { super.onResume(); if (api.configured() && ::connectionStatus.isInitialized) connectionStatus.text = "● ${api.rememberedConnectionLabel()}" }
    override fun onPause() { if (::web.isInitialized) web.onPause(); super.onPause() }
    override fun onDestroy() { discovery.stop(); if (::web.isInitialized) web.destroy(); tts?.stop(); tts?.shutdown(); super.onDestroy() }
}
