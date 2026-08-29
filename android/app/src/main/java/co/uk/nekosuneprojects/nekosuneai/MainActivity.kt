package co.uk.nekosuneprojects.nekosuneai

import android.Manifest
import android.content.Intent
import android.graphics.Color
import android.graphics.Typeface
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.speech.RecognizerIntent
import android.speech.tts.TextToSpeech
import android.text.InputType
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.splashscreen.SplashScreen.Companion.installSplashScreen
import com.google.android.material.button.MaterialButton
import com.google.android.material.card.MaterialCardView
import java.net.URLEncoder
import java.util.Locale
import kotlin.concurrent.thread

class MainActivity : AppCompatActivity(), TextToSpeech.OnInitListener {
    private lateinit var api: ApiClient
    private lateinit var prefs: android.content.SharedPreferences
    private lateinit var web: WebView
    private lateinit var chatInput: EditText
    private lateinit var replyView: TextView
    private lateinit var connectionStatus: TextView
    private var tts: TextToSpeech? = null

    private val bg = Color.rgb(13, 11, 18)
    private val surface = Color.rgb(23, 19, 31)
    private val surface2 = Color.rgb(33, 26, 44)
    private val primary = Color.rgb(184, 156, 255)
    private val text = Color.rgb(247, 241, 255)
    private val muted = Color.rgb(185, 175, 199)
    private val success = Color.rgb(121, 216, 167)

    private val askNotifications = registerForActivityResult(ActivityResultContracts.RequestPermission()) {}
    private val speechLauncher = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        if (result.resultCode == RESULT_OK) {
            val spoken = result.data?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)?.firstOrNull().orEmpty()
            if (spoken.isNotBlank()) { chatInput.setText(spoken); sendChat(spoken) }
        }
    }

    override fun onInit(status: Int) { if (status == TextToSpeech.SUCCESS) tts?.language = Locale.UK }

    override fun onCreate(savedInstanceState: Bundle?) {
        val splash = installSplashScreen()
        super.onCreate(savedInstanceState)
        splash.setOnExitAnimationListener { provider ->
            provider.view.animate()
                .alpha(0f)
                .scaleX(1.12f)
                .scaleY(1.12f)
                .setDuration(420L)
                .withEndAction { provider.remove() }
                .start()
        }

        window.statusBarColor = bg
        window.navigationBarColor = bg
        api = ApiClient(this)
        prefs = getSharedPreferences("neko", MODE_PRIVATE)
        tts = TextToSpeech(this, this)

        val content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(18), dp(18), dp(18), dp(36))
            setBackgroundColor(bg)
        }
        val scroll = ScrollView(this).apply {
            isFillViewport = true
            setBackgroundColor(bg)
            addView(content)
        }

        content.addView(hero())
        content.addView(space(14))

        val server = styledInput("Pi address", "https://neko.example.com", InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI).apply {
            setText(prefs.getString("server_url", ""))
        }
        val token = styledInput("Dashboard token", "WEB_DASHBOARD_TOKEN", InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD).apply {
            setText(prefs.getString("token", ""))
        }

        content.addView(card("Connection", "Secure link to your Raspberry Pi") { body ->
            body.addView(server)
            body.addView(space(10))
            body.addView(token)
            body.addView(space(12))
            body.addView(primaryButton("Connect to Pi") {
                api.save(server.text.toString(), token.text.toString())
                ContextCompat.startForegroundService(this@MainActivity, Intent(this@MainActivity, CompanionService::class.java))
                if (Build.VERSION.SDK_INT >= 33) askNotifications.launch(Manifest.permission.POST_NOTIFICATIONS)
                connectionStatus.text = "● Connected"
                connectionStatus.setTextColor(success)
                loadAvatarFromPi()
            })
        })

        content.addView(space(14))
        content.addView(card("Talk to Neko", "Voice, text and camera companion controls") { body ->
            replyView = TextView(this).apply {
                text = "Ready when you are."
                textSize = 15f
                setTextColor(text)
                setPadding(dp(14), dp(12), dp(14), dp(12))
                setBackgroundColor(surface2)
            }
            body.addView(replyView, matchWrap())
            body.addView(space(12))

            chatInput = styledInput("Message Neko", "Ask me anything…", InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_MULTI_LINE).apply {
                minLines = 2
                maxLines = 5
            }
            body.addView(chatInput)
            body.addView(space(10))
            body.addView(primaryButton("Send message") { sendChat(chatInput.text.toString()) })
            body.addView(space(8))
            body.addView(secondaryButton("🎤  Talk to Neko") {
                val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                    putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                    putExtra(RecognizerIntent.EXTRA_LANGUAGE, Locale.getDefault())
                    putExtra(RecognizerIntent.EXTRA_PROMPT, "Talk to NekoSuneAI")
                }
                speechLauncher.launch(intent)
            })
            body.addView(space(8))
            body.addView(secondaryButton("📷  Share phone camera") {
                if (!api.configured()) replyView.text = "Connect to the Pi first."
                else startActivity(Intent(this@MainActivity, CameraVisionActivity::class.java))
            })
            body.addView(TextView(this).apply {
                text = "Camera sharing is opt-in and stops as soon as you leave the camera screen."
                textSize = 12f
                setTextColor(muted)
                setPadding(0, dp(10), 0, 0)
            })
        })

        content.addView(space(14))
        content.addView(card("Neko avatar", "Live VRM rendered from your Pi") { body ->
            val avatarFrame = FrameLayout(this).apply {
                setBackgroundColor(Color.BLACK)
                clipToOutline = true
            }
            web = WebView(this).apply {
                layoutParams = FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(420))
                settings.javaScriptEnabled = true
                settings.domStorageEnabled = true
                setBackgroundColor(Color.TRANSPARENT)
                webViewClient = WebViewClient()
            }
            avatarFrame.addView(web)
            body.addView(avatarFrame, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(420)))
            body.addView(space(10))
            body.addView(secondaryButton("↻  Reload avatar") { loadAvatarFromPi() })
        })

        content.addView(space(14))
        content.addView(card("Phone tools", "Useful remote companion features") { body ->
            body.addView(secondaryButton("🔔  Notification access") {
                startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
            })
            body.addView(space(8))
            body.addView(secondaryButton("📱  Test Find My Phone") {
                ContextCompat.startForegroundService(this@MainActivity, Intent(this@MainActivity, FindPhoneService::class.java).apply { action = FindPhoneService.ACTION_START })
            })
            body.addView(space(8))
            body.addView(secondaryButton("■  Stop ringing") {
                startService(Intent(this@MainActivity, FindPhoneService::class.java).apply { action = FindPhoneService.ACTION_STOP })
            })
        })

        content.addView(TextView(this).apply {
            text = "For remote use, connect through Tailscale/VPN or authenticated HTTPS. The VRM renderer pauses when this screen is closed so background monitoring stays lightweight."
            textSize = 12f
            setTextColor(muted)
            setPadding(dp(4), dp(18), dp(4), dp(8))
        })

        setContentView(scroll)
        if (api.configured()) {
            connectionStatus.text = "● Saved connection"
            connectionStatus.setTextColor(success)
            loadAvatarFromPi()
        }
    }

    private fun hero(): View = LinearLayout(this).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
        setPadding(dp(4), dp(8), dp(4), dp(4))

        addView(ImageView(this@MainActivity).apply {
            setImageResource(R.drawable.ic_neko_logo)
            contentDescription = "NekoSuneAI"
        }, LinearLayout.LayoutParams(dp(66), dp(66)))

        addView(LinearLayout(this@MainActivity).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(12), 0, 0, 0)
            addView(TextView(this@MainActivity).apply {
                text = "NekoSuneAI"
                textSize = 26f
                setTextColor(text)
                setTypeface(typeface, Typeface.BOLD)
            })
            addView(TextView(this@MainActivity).apply {
                text = "Android Companion"
                textSize = 14f
                setTextColor(primary)
            })
            connectionStatus = TextView(this@MainActivity).apply {
                text = "● Not connected"
                textSize = 12f
                setTextColor(muted)
                setPadding(0, dp(4), 0, 0)
            }
            addView(connectionStatus)
        }, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
    }

    private fun card(title: String, subtitle: String, build: (LinearLayout) -> Unit): MaterialCardView {
        val card = MaterialCardView(this).apply {
            radius = dp(20).toFloat()
            cardElevation = 0f
            setCardBackgroundColor(surface)
            strokeColor = Color.rgb(48, 39, 63)
            strokeWidth = dp(1)
        }
        val body = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(18), dp(18), dp(18), dp(18))
        }
        body.addView(TextView(this).apply {
            text = title
            textSize = 20f
            setTextColor(text)
            setTypeface(typeface, Typeface.BOLD)
        })
        body.addView(TextView(this).apply {
            text = subtitle
            textSize = 13f
            setTextColor(muted)
            setPadding(0, dp(3), 0, dp(14))
        })
        build(body)
        card.addView(body)
        return card
    }

    private fun styledInput(label: String, hintText: String, inputTypeValue: Int): EditText = EditText(this).apply {
        hint = "$label · $hintText"
        inputType = inputTypeValue
        textSize = 15f
        setTextColor(text)
        setHintTextColor(Color.rgb(130, 119, 147))
        setPadding(dp(14), dp(12), dp(14), dp(12))
        setSingleLine(inputTypeValue and InputType.TYPE_TEXT_FLAG_MULTI_LINE == 0)
        backgroundTintList = android.content.res.ColorStateList.valueOf(primary)
    }

    private fun primaryButton(label: String, onClick: () -> Unit): MaterialButton = MaterialButton(this).apply {
        text = label
        textSize = 14f
        isAllCaps = false
        setTextColor(bg)
        setBackgroundColor(primary)
        cornerRadius = dp(14)
        layoutParams = matchWrap()
        setOnClickListener { onClick() }
    }

    private fun secondaryButton(label: String, onClick: () -> Unit): MaterialButton = MaterialButton(this).apply {
        text = label
        textSize = 14f
        isAllCaps = false
        setTextColor(text)
        setBackgroundColor(surface2)
        cornerRadius = dp(14)
        layoutParams = matchWrap()
        setOnClickListener { onClick() }
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
        val message = value.trim()
        if (message.isBlank()) return
        if (!api.configured()) {
            replyView.text = "Connect to the Pi first."
            return
        }
        replyView.text = "Neko is thinking…"
        web.evaluateJavascript("window.setNekoEmotion('neutral');window.setNekoGesture('idle');window.setNekoSpeaking(false);", null)
        thread(name = "NekoRemoteChat") {
            val answer = try { api.chat(message) } catch (e: Exception) { ChatReply("I couldn't reach the Pi: ${e.message}") }
            runOnUiThread {
                replyView.text = answer.text
                chatInput.setText("")
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
        val step = (duration / vowels.length.coerceAtLeast(1)).coerceIn(55L, 150L)
        web.evaluateJavascript("window.setNekoSpeaking(true);", null)
        vowels.forEachIndexed { i, c ->
            val vis = when (c) { 'a' -> "aa"; 'e' -> "ee"; 'i','y' -> "ih"; 'o' -> "oh"; else -> "ou" }
            web.postDelayed({ web.evaluateJavascript("window.setNekoViseme('$vis',0.72);", null) }, i * step)
        }
        web.postDelayed({ web.evaluateJavascript("window.setNekoViseme('',0);window.setNekoSpeaking(false);window.setNekoGesture('idle');", null) }, duration)
    }

    private fun safeJs(value: String): String = value.replace("'", "").replace("\\", "").take(24)
    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()
    private fun space(height: Int): View = View(this).apply { layoutParams = LinearLayout.LayoutParams(1, dp(height)) }
    private fun matchWrap() = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)

    override fun onPause() { if (::web.isInitialized) web.onPause(); super.onPause() }
    override fun onResume() { super.onResume(); if (::web.isInitialized) web.onResume() }
    override fun onDestroy() { tts?.stop(); tts?.shutdown(); if (::web.isInitialized) web.destroy(); super.onDestroy() }
}
