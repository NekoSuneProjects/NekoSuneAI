package co.uk.nekosuneprojects.nekosuneai

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.telecom.Call
import android.telecom.CallScreeningService
import android.telephony.SmsManager
import androidx.core.app.NotificationCompat
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.util.concurrent.TimeUnit
import kotlin.concurrent.thread

class ScamCallScreeningService : CallScreeningService() {
    private val client = OkHttpClient.Builder()
        .connectTimeout(6, TimeUnit.SECONDS)
        .readTimeout(25, TimeUnit.SECONDS)
        .build()

    override fun onScreenCall(callDetails: Call.Details) {
        // Never delay or block a real call while the reputation lookup runs.
        respondToCall(
            callDetails,
            CallResponse.Builder()
                .setDisallowCall(false)
                .setRejectCall(false)
                .setSilenceCall(false)
                .setSkipCallLog(false)
                .setSkipNotification(false)
                .build()
        )

        if (callDetails.callDirection != Call.Details.DIRECTION_INCOMING) return
        val number = callDetails.handle?.schemeSpecificPart.orEmpty().trim()
        if (number.isBlank()) return

        thread(name = "NekoScamLookup", isDaemon = true) {
            try {
                val result = lookup(number)
                if (!result.optBoolean("flagged", false)) return@thread
                notifyFlagged(number, result)
                maybeSendReply(number, result)
            } catch (_: Exception) {
                // A failed public-web lookup must never interfere with the call.
            }
        }
    }

    private fun lookup(number: String): JSONObject {
        val prefs = getSharedPreferences("neko", Context.MODE_PRIVATE)
        val server = prefs.getString("server_url", "").orEmpty().trim().trimEnd('/')
        val deviceToken = prefs.getString("device_token", "").orEmpty()
        val legacyToken = prefs.getString("token", "").orEmpty()
        if (!server.startsWith("http") || (deviceToken.isBlank() && legacyToken.isBlank())) {
            throw IllegalStateException("NekoSuneAI server is not paired")
        }
        val deviceId = prefs.getString("device_id", "").orEmpty()
        val payload = JSONObject().apply {
            put("number", number)
            put("region", java.util.Locale.getDefault().country.ifBlank { "GB" })
            put("device_id", deviceId)
            put("device_name", "${android.os.Build.MANUFACTURER} ${android.os.Build.MODEL}")
        }
        val builder = Request.Builder()
            .url("$server/api/android/scam-call")
            .post(payload.toString().toRequestBody("application/json".toMediaType()))
        if (deviceToken.isNotBlank()) builder.header("X-Neko-Device-Token", deviceToken)
        else builder.header("X-Neko-Token", legacyToken)
        client.newCall(builder.build()).execute().use { response ->
            val raw = response.body?.string().orEmpty()
            val json = JSONObject(raw.ifBlank { "{}" })
            if (!response.isSuccessful) throw IllegalStateException(json.optString("error", "Lookup failed"))
            return json
        }
    }

    private fun notifyFlagged(number: String, result: JSONObject) {
        val channelId = "neko_scam_calls"
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(
            NotificationChannel(channelId, "Flagged incoming calls", NotificationManager.IMPORTANCE_HIGH)
        )
        val carrier = result.optString("carrier", "").ifBlank { "Unknown carrier" }
        val location = result.optString("location", "").ifBlank { "Unknown location" }
        manager.notify(
            (number.hashCode() and 0x7fffffff),
            NotificationCompat.Builder(this, channelId)
                .setSmallIcon(R.mipmap.ic_launcher)
                .setContentTitle("Possible scam/spam caller")
                .setContentText("$number · $carrier · $location")
                .setStyle(NotificationCompat.BigTextStyle().bigText(result.optString("summary", "Public reputation reports flagged this number.")))
                .setAutoCancel(true)
                .build()
        )
    }

    private fun maybeSendReply(number: String, result: JSONObject) {
        val prefs = getSharedPreferences("neko", Context.MODE_PRIVATE)
        if (!prefs.getBoolean("scam_auto_sms", false)) return
        if (checkSelfPermission(android.Manifest.permission.SEND_SMS) != android.content.pm.PackageManager.PERMISSION_GRANTED) return

        // Avoid repeated paid SMS messages to the same number in a short period.
        val key = "scam_sms_${number.hashCode()}"
        val now = System.currentTimeMillis()
        val last = prefs.getLong(key, 0L)
        if (now - last < 24L * 60L * 60L * 1000L) return

        val template = prefs.getString(
            "scam_sms_template",
            "This number was flagged by my call-screening system as possible spam/scam. Please do not contact this number again."
        ).orEmpty().trim()
        if (template.isBlank()) return

        val risk = result.optString("risk", "possible")
        val message = template
            .replace("{number}", number)
            .replace("{risk}", risk)
            .take(480)
        try {
            @Suppress("DEPRECATION")
            SmsManager.getDefault().sendTextMessage(number, null, message, null, null)
            prefs.edit().putLong(key, now).apply()
        } catch (_: Exception) {
            // Carrier/device restrictions can deny SEND_SMS; keep screening working.
        }
    }
}
