package co.uk.nekosuneprojects.nekosuneai

import android.Manifest
import android.app.role.RoleManager
import android.content.Intent
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.provider.Settings
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity

class ScamCallSettingsActivity : AppCompatActivity() {
    private val prefs by lazy { getSharedPreferences("neko", MODE_PRIVATE) }
    private lateinit var status: TextView
    private lateinit var autoSms: CheckBox
    private lateinit var template: EditText

    private val bg = Color.parseColor("#080914")
    private val surface = Color.parseColor("#111329")
    private val border = Color.parseColor("#292D55")
    private val textColor = Color.parseColor("#F4F2FF")
    private val muted = Color.parseColor("#B3B7DC")
    private val violet = Color.parseColor("#A78BFA")
    private val cyan = Color.parseColor("#67E8F9")

    private val roleLauncher = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { refreshStatus() }
    private val smsPermission = registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (!granted) autoSms.isChecked = false
        save()
        refreshStatus()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.statusBarColor = bg
        window.navigationBarColor = bg

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(16), dp(18), dp(16), dp(30))
            setBackgroundColor(bg)
        }
        val scroll = ScrollView(this).apply { addView(root); setBackgroundColor(bg) }

        root.addView(TextView(this).apply { text = "CALL PROTECTION"; textSize = 10f; letterSpacing = .13f; typeface = Typeface.DEFAULT_BOLD; setTextColor(violet) })
        root.addView(TextView(this).apply { text = "Scam caller checker"; textSize = 24f; typeface = Typeface.DEFAULT_BOLD; setTextColor(textColor); setPadding(0, dp(4), 0, dp(4)) })
        root.addView(TextView(this).apply { text = "Incoming numbers are checked by your paired Docker NekoSuneAI against public web reputation results. Android provides the number through its protected caller ID and spam role, so NekoSuneAI does not request your contacts or full call history. Only flagged calls are stored in the Docker dashboard."; textSize = 13f; setTextColor(muted) })

        status = TextView(this).apply { setPadding(dp(12), dp(10), dp(12), dp(10)); setTextColor(cyan); background = rounded(Color.parseColor("#17213A"), Color.parseColor("#345D77"), 12) }
        root.addView(status, params(14))

        val enable = Button(this).apply {
            text = "Enable incoming-call screening"
            isAllCaps = false
            setTextColor(Color.parseColor("#111329"))
            typeface = Typeface.DEFAULT_BOLD
            background = rounded(violet, cyan, 12)
            setOnClickListener { requestScreeningRole() }
        }
        root.addView(enable, params(12))

        autoSms = CheckBox(this).apply {
            text = "Automatically text callers that are flagged"
            setTextColor(textColor)
            isChecked = prefs.getBoolean("scam_auto_sms", false)
            setOnCheckedChangeListener { _, checked ->
                if (checked && checkSelfPermission(Manifest.permission.SEND_SMS) != android.content.pm.PackageManager.PERMISSION_GRANTED) {
                    smsPermission.launch(Manifest.permission.SEND_SMS)
                } else save()
            }
        }
        root.addView(autoSms, params(14))

        root.addView(TextView(this).apply {
            text = "Auto reply is optional and OFF by default. Your mobile carrier may charge for SMS. Some Android installs may restrict SMS permission; call checking still works without it."
            textSize = 11f
            setTextColor(muted)
        }, params(4))

        template = EditText(this).apply {
            minLines = 4
            setTextColor(textColor)
            setHintTextColor(Color.parseColor("#777DA9"))
            hint = "Auto-reply message"
            setText(prefs.getString("scam_sms_template", DEFAULT_TEMPLATE))
            background = rounded(Color.parseColor("#0D0F24"), Color.parseColor("#343961"), 10)
            setPadding(dp(12), dp(10), dp(12), dp(10))
        }
        root.addView(template, params(10))

        root.addView(Button(this).apply {
            text = "Save call settings"
            isAllCaps = false
            setTextColor(textColor)
            background = rounded(Color.parseColor("#181B38"), Color.parseColor("#3C4275"), 12)
            setOnClickListener { save(); refreshStatus() }
        }, params(10))

        root.addView(Button(this).apply {
            text = "Open Android default-app / call settings"
            isAllCaps = false
            setTextColor(textColor)
            background = rounded(Color.parseColor("#181B38"), Color.parseColor("#3C4275"), 12)
            setOnClickListener { startActivity(Intent(Settings.ACTION_MANAGE_DEFAULT_APPS_SETTINGS)) }
        }, params(8))

        root.addView(TextView(this).apply {
            text = "NekoSuneAI does not automatically block calls. Reputation results are community/public-web signals, not proof of fraud. The Docker export is intended as a reviewable blocklist for you or a friend."
            textSize = 11f
            setTextColor(muted)
        }, params(14))

        setContentView(scroll)
        refreshStatus()
        if (intent.getBooleanExtra("enable_now", false)) requestScreeningRole()
    }

    private fun requestScreeningRole() {
        val rm = getSystemService(RoleManager::class.java)
        if (!rm.isRoleAvailable(RoleManager.ROLE_CALL_SCREENING)) {
            status.text = "● Call-screening role is unavailable on this phone."
            return
        }
        if (rm.isRoleHeld(RoleManager.ROLE_CALL_SCREENING)) {
            refreshStatus()
            return
        }
        roleLauncher.launch(rm.createRequestRoleIntent(RoleManager.ROLE_CALL_SCREENING))
    }

    private fun save() {
        prefs.edit()
            .putBoolean("scam_auto_sms", autoSms.isChecked)
            .putString("scam_sms_template", template.text.toString().trim().ifBlank { DEFAULT_TEMPLATE })
            .apply()
    }

    private fun refreshStatus() {
        val rm = getSystemService(RoleManager::class.java)
        val held = rm.isRoleAvailable(RoleManager.ROLE_CALL_SCREENING) && rm.isRoleHeld(RoleManager.ROLE_CALL_SCREENING)
        val sms = checkSelfPermission(Manifest.permission.SEND_SMS) == android.content.pm.PackageManager.PERMISSION_GRANTED
        status.text = if (held) {
            "● Incoming-call screening ON${if (autoSms.isChecked && sms) " · auto reply ON" else ""}"
        } else {
            "● Incoming-call screening OFF — tap Enable"
        }
    }

    private fun rounded(fill: Int, stroke: Int, radius: Int) = GradientDrawable().apply {
        shape = GradientDrawable.RECTANGLE; setColor(fill); cornerRadius = dp(radius).toFloat(); setStroke(dp(1), stroke)
    }
    private fun params(top: Int) = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply { topMargin = dp(top) }
    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()

    companion object {
        const val DEFAULT_TEMPLATE = "This number was flagged by my call-screening system as possible spam/scam. Please do not contact this number again."
    }
}
