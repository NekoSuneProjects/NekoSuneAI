package co.uk.nekosuneprojects.nekosuneai

import android.Manifest
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.provider.Settings
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

class MainActivity : AppCompatActivity() {
    private lateinit var api: ApiClient
    private lateinit var prefs: android.content.SharedPreferences

    private val askNotifications = registerForActivityResult(ActivityResultContracts.RequestPermission()) {}

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        api = ApiClient(this)
        prefs = getSharedPreferences("neko", MODE_PRIVATE)

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(32, 32, 32, 32)
        }
        val scroll = ScrollView(this).apply { addView(root) }

        root.addView(TextView(this).apply {
            text = "NekoSuneAI Android Companion"
            textSize = 24f
        })
        root.addView(TextView(this).apply {
            text = "Low-power link to your Raspberry Pi assistant"
            textSize = 14f
        })

        val server = EditText(this).apply {
            hint = "Pi URL, e.g. https://neko.example.com"
            setText(prefs.getString("server_url", ""))
        }
        val token = EditText(this).apply {
            hint = "WEB_DASHBOARD_TOKEN"
            setText(prefs.getString("token", ""))
        }
        root.addView(server)
        root.addView(token)

        root.addView(Button(this).apply {
            text = "Save + Connect"
            setOnClickListener {
                api.save(server.text.toString(), token.text.toString())
                ContextCompat.startForegroundService(this@MainActivity, Intent(this@MainActivity, CompanionService::class.java))
                if (Build.VERSION.SDK_INT >= 33) askNotifications.launch(Manifest.permission.POST_NOTIFICATIONS)
            }
        })

        root.addView(Button(this).apply {
            text = "Allow notification/SMS-style alerts"
            setOnClickListener { startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS)) }
        })

        root.addView(Button(this).apply {
            text = "Test Find My Phone"
            setOnClickListener {
                ContextCompat.startForegroundService(this@MainActivity, Intent(this@MainActivity, FindPhoneService::class.java).apply {
                    action = FindPhoneService.ACTION_START
                })
            }
        })

        root.addView(Button(this).apply {
            text = "STOP ringing"
            setOnClickListener {
                startService(Intent(this@MainActivity, FindPhoneService::class.java).apply { action = FindPhoneService.ACTION_STOP })
            }
        })

        root.addView(TextView(this).apply {
            text = "VRM Avatar"
            textSize = 20f
            setPadding(0, 28, 0, 8)
        })
        val modelUrl = EditText(this).apply {
            hint = "https://.../avatar.vrm"
            setText(prefs.getString("vrm_url", ""))
        }
        root.addView(modelUrl)

        val web = WebView(this).apply {
            layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 900)
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            webViewClient = WebViewClient()
        }
        root.addView(Button(this).apply {
            text = "Load VRM"
            setOnClickListener {
                val url = modelUrl.text.toString().trim()
                prefs.edit().putString("vrm_url", url).apply()
                web.loadUrl("file:///android_asset/avatar/index.html?model=" + java.net.URLEncoder.encode(url, "UTF-8"))
            }
        })
        root.addView(web)

        root.addView(TextView(this).apply {
            text = "Privacy: notification access is optional. Message previews can be disabled later so the Pi only receives the app/name plus 'New notification'. The companion service uses long-polling plus a five-minute telemetry heartbeat to minimise heat and battery use."
            textSize = 12f
            setPadding(0, 20, 0, 40)
        })

        setContentView(scroll)
    }
}
