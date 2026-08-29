package co.uk.nekosuneprojects.nekosuneai

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.view.Gravity
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat

class WakeWordSettingsActivity : AppCompatActivity() {
    private lateinit var phraseInput: EditText
    private lateinit var status: TextView
    private val prefs by lazy { getSharedPreferences("neko", MODE_PRIVATE) }

    private val requestMic = registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) enableWake() else status.text = "Microphone permission is required for background wake listening."
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val bg = Color.parseColor("#080914")
        val surface = Color.parseColor("#111329")
        val border = Color.parseColor("#292D55")
        val text = Color.parseColor("#F4F2FF")
        val muted = Color.parseColor("#B3B7DC")
        val violet = Color.parseColor("#A78BFA")
        val cyan = Color.parseColor("#67E8F9")
        window.statusBarColor = bg
        window.navigationBarColor = bg

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(20), dp(28), dp(20), dp(28))
            setBackgroundColor(bg)
        }
        root.addView(TextView(this).apply { this.text = "BACKGROUND VOICE"; textSize = 10f; letterSpacing = .14f; setTextColor(violet); typeface = Typeface.DEFAULT_BOLD })
        root.addView(TextView(this).apply { this.text = "Hey Jarvis"; textSize = 27f; setTextColor(text); typeface = Typeface.DEFAULT_BOLD; setPadding(0, dp(5), 0, dp(5)) })
        root.addView(TextView(this).apply {
            this.text = "Keep NekoSuneAI listening in the background. Say the wake phrase, then speak your request. The request is sent to the same paired Docker-hosted AI and the reply is spoken on your phone."
            textSize = 13f; setTextColor(muted); setLineSpacing(0f, 1.15f)
        })

        val card = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dp(16), dp(16), dp(16), dp(16)); background = rounded(surface, border, 16) }
        card.addView(TextView(this).apply { this.text = "Wake phrase"; textSize = 12f; setTextColor(text); typeface = Typeface.DEFAULT_BOLD })
        phraseInput = EditText(this).apply {
            setText(prefs.getString("wake_phrase", WakeWordService.DEFAULT_WAKE_PHRASE) ?: WakeWordService.DEFAULT_WAKE_PHRASE)
            hint = "hey jarvis"
            setTextColor(text); setHintTextColor(Color.parseColor("#777DA9")); textSize = 15f
            setPadding(dp(12), dp(11), dp(12), dp(11)); background = rounded(Color.parseColor("#0D0F24"), Color.parseColor("#343961"), 11)
        }
        card.addView(phraseInput, params(10))
        status = TextView(this).apply {
            val enabled = prefs.getBoolean("wake_word_enabled", false)
            this.text = if (enabled) "● Background wake is ON" else "● Background wake is OFF"
            textSize = 12f; setTextColor(cyan); setPadding(0, dp(12), 0, dp(4))
        }
        card.addView(status)
        card.addView(Button(this).apply {
            text = "Enable background wake"; isAllCaps = false; typeface = Typeface.DEFAULT_BOLD; textSize = 14f; setTextColor(Color.parseColor("#111329")); background = rounded(violet, cyan, 12); gravity = Gravity.CENTER
            setOnClickListener { savePhrase(); ensurePermissionAndEnable() }
        }, params(10))
        card.addView(Button(this).apply {
            text = "Turn off background wake"; isAllCaps = false; textSize = 14f; setTextColor(text); background = rounded(Color.parseColor("#181B38"), Color.parseColor("#3C4275"), 12)
            setOnClickListener {
                prefs.edit().putBoolean("wake_word_enabled", false).apply()
                stopService(Intent(this@WakeWordSettingsActivity, WakeWordService::class.java))
                status.text = "● Background wake is OFF"
            }
        }, params(8))
        card.addView(TextView(this).apply {
            this.text = "A persistent Android notification is shown while the microphone listener is active. Android may stop background listening if battery optimisation force-stops the app."
            textSize = 11f; setTextColor(muted); setPadding(0, dp(12), 0, 0)
        })
        root.addView(card, params(18))
        setContentView(root)

        if (intent.getBooleanExtra("enable_now", false)) ensurePermissionAndEnable()
    }

    private fun savePhrase() {
        val phrase = phraseInput.text.toString().trim().lowercase().ifBlank { WakeWordService.DEFAULT_WAKE_PHRASE }
        prefs.edit().putString("wake_phrase", phrase).apply()
    }

    private fun ensurePermissionAndEnable() {
        savePhrase()
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) enableWake()
        else requestMic.launch(Manifest.permission.RECORD_AUDIO)
    }

    private fun enableWake() {
        prefs.edit().putBoolean("wake_word_enabled", true).apply()
        ContextCompat.startForegroundService(this, Intent(this, WakeWordService::class.java))
        status.text = "● Background wake is ON · say “${prefs.getString("wake_phrase", WakeWordService.DEFAULT_WAKE_PHRASE)}”"
    }

    private fun rounded(fill: Int, stroke: Int, radius: Int) = GradientDrawable().apply {
        shape = GradientDrawable.RECTANGLE; setColor(fill); cornerRadius = dp(radius).toFloat(); setStroke(dp(1), stroke)
    }
    private fun params(top: Int = 0) = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply { topMargin = dp(top) }
    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()
}
