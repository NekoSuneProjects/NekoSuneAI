package co.uk.nekosuneprojects.nekosuneai

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.content.pm.PackageManager
import android.telephony.SmsManager
import androidx.core.app.NotificationCompat
import androidx.work.Worker
import androidx.work.WorkerParameters
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.util.Locale
import java.util.concurrent.TimeUnit

/**
 * Reliable background delivery for numbers received by CallScreeningService.
 * Android may tear down the screening service immediately after respondToCall(),
 * so the old daemon-thread implementation could disappear before HTTP reached Docker.
 */
class ScamCallLookupWorker(appContext: Context, params: WorkerParameters) : Worker(appContext, params) {
    private val prefs = applicationContext.getSharedPreferences("neko", Context.MODE_PRIVATE)
    private val client = OkHttpClient.Builder()
        .connectTimeout(8, TimeUnit.SECONDS)
        .readTimeout(35, TimeUnit.SECONDS)
        .writeTimeout(12, TimeUnit.SECONDS)
        .build()

    override fun doWork(): Result {
        val number = inputData.getString(KEY_NUMBER).orEmpty().trim()
        if (number.isBlank()) return Result.failure()
        return try {
            markSync(number, "sending")
            val result = lookup(number)
            val state = when {
                result.optBoolean("flagged", false) -> "scam"
                result.optBoolean("important", false) || result.optBoolean("verified", false) -> "important"
                else -> "unknown"
            }
            markSync(number, "ok:$state")
            notifyCaller(number, result, state)
            if (state == "scam") maybeSendReply(number, result)
            Result.success()
        } catch (exc: Exception) {
            markSync(number, "failed:${exc.message.orEmpty().take(120)}")
            if (runAttemptCount < 4) Result.retry() else Result.failure()
        }
    }

    private fun lookup(number: String): JSONObject {
        val server = prefs.getString("server_url", "").orEmpty().trim().trimEnd('/')
        val deviceToken = prefs.getString("device_token", "").orEmpty()
        val legacyToken = prefs.getString("token", "").orEmpty()
        if (!server.startsWith("http") || (deviceToken.isBlank() && legacyToken.isBlank())) {
            throw IllegalStateException("phone is not paired to Docker")
        }
        val payload = JSONObject().apply {
            put("number", number)
            put("region", Locale.getDefault().country.ifBlank { "GB" })
            put("device_id", prefs.getString("device_id", "").orEmpty())
            put("device_name", "${android.os.Build.MANUFACTURER} ${android.os.Build.MODEL}")
            put("source", "android-call-screening")
            put("app_version", BuildConfig.VERSION_NAME)
        }
        val request = Request.Builder()
            .url("$server/api/android/scam-call")
            .post(payload.toString().toRequestBody("application/json".toMediaType()))
            .apply {
                if (deviceToken.isNotBlank()) header("X-Neko-Device-Token", deviceToken)
                else header("X-Neko-Token", legacyToken)
            }
            .build()
        client.newCall(request).execute().use { response ->
            val raw = response.body?.string().orEmpty()
            val root = JSONObject(raw.ifBlank { "{}" })
            if (!response.isSuccessful) {
                throw IllegalStateException(root.optString("error", "Docker HTTP ${response.code}"))
            }
            return root
        }
    }

    private fun notifyCaller(number: String, result: JSONObject, state: String) {
        val manager = applicationContext.getSystemService(NotificationManager::class.java)
        val channelId = "neko_call_identity"
        manager.createNotificationChannel(
            NotificationChannel(channelId, "Incoming caller identity", NotificationManager.IMPORTANCE_HIGH)
        )
        val carrier = result.optString("carrier", "").ifBlank { "Unknown provider" }
        val location = result.optString("location", "").ifBlank { result.optString("country_code", "Unknown location") }
        val organisation = result.optString("organisation", "").ifBlank { result.optString("identity_name", "") }
        val title = when (state) {
            "scam" -> "⚠ Possible scam/spam caller"
            "important" -> "✓ Verified / important caller${if (organisation.isNotBlank()) ": $organisation" else ""}"
            else -> "Unknown caller — be careful"
        }
        val fallback = when (state) {
            "scam" -> "Public reputation signals flagged this number."
            "important" -> "This number matched a trusted/verified caller record."
            else -> "This number is not currently verified as important and is not flagged as scam."
        }
        val summary = result.optString("summary", "").ifBlank { fallback }
        manager.notify(
            (number.hashCode() and 0x7fffffff),
            NotificationCompat.Builder(applicationContext, channelId)
                .setSmallIcon(R.mipmap.ic_launcher)
                .setContentTitle(title)
                .setContentText("$number · $carrier · $location")
                .setStyle(NotificationCompat.BigTextStyle().bigText("$summary\n$number · $carrier · $location"))
                .setPriority(NotificationCompat.PRIORITY_HIGH)
                .setAutoCancel(true)
                .build()
        )
    }

    private fun maybeSendReply(number: String, result: JSONObject) {
        if (!prefs.getBoolean("scam_auto_sms", false)) return
        if (applicationContext.checkSelfPermission(Manifest.permission.SEND_SMS) != PackageManager.PERMISSION_GRANTED) return
        val key = "scam_sms_${number.hashCode()}"
        val now = System.currentTimeMillis()
        if (now - prefs.getLong(key, 0L) < 24L * 60L * 60L * 1000L) return
        val template = prefs.getString("scam_sms_template", ScamCallSettingsActivity.DEFAULT_TEMPLATE).orEmpty().trim()
        if (template.isBlank()) return
        val message = template
            .replace("{number}", number)
            .replace("{risk}", result.optString("risk", "possible"))
            .take(480)
        try {
            @Suppress("DEPRECATION")
            SmsManager.getDefault().sendTextMessage(number, null, message, null, null)
            prefs.edit().putLong(key, now).apply()
        } catch (_: Exception) { }
    }

    private fun markSync(number: String, status: String) {
        prefs.edit()
            .putString("call_last_sync_number", number)
            .putString("call_last_sync_status", status)
            .putLong("call_last_sync_at", System.currentTimeMillis())
            .apply()
    }

    companion object {
        const val KEY_NUMBER = "number"
    }
}
