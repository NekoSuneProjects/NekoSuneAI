package co.uk.nekosuneprojects.nekosuneai

import android.app.ActivityManager
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager
import android.os.Build
import android.os.Environment
import android.os.PowerManager
import android.os.StatFs
import android.util.Base64
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.util.UUID
import java.util.concurrent.TimeUnit

data class ChatReply(val text: String, val emotion: String = "neutral", val gesture: String = "idle")
data class PairingRequest(val requestId: String, val serverUrl: String)
data class PairingResult(val status: String, val connected: Boolean = false)

class ApiClient(private val context: Context) {
    private val prefs = context.getSharedPreferences("neko", Context.MODE_PRIVATE)
    private val client = OkHttpClient.Builder().connectTimeout(6, TimeUnit.SECONDS).readTimeout(90, TimeUnit.SECONDS).build()

    val deviceId: String
        get() = prefs.getString("device_id", null) ?: UUID.randomUUID().toString().also { prefs.edit().putString("device_id", it).apply() }

    val serverUrl: String get() = (prefs.getString("server_url", "") ?: "").trimEnd('/')
    private val deviceToken: String get() = prefs.getString("device_token", "") ?: ""
    private val legacyToken: String get() = prefs.getString("token", "") ?: ""
    private val token: String get() = deviceToken.ifBlank { legacyToken }

    fun configured(): Boolean = serverUrl.startsWith("http") && token.isNotBlank()
    fun pairedAutomatically(): Boolean = serverUrl.startsWith("http") && deviceToken.isNotBlank()

    fun save(server: String, authToken: String) {
        prefs.edit()
            .putString("server_url", server.trim().trimEnd('/'))
            .putString("token", authToken.trim())
            .remove("device_token")
            .apply()
    }

    fun clearConnection() {
        prefs.edit().remove("server_url").remove("token").remove("device_token").apply()
    }

    fun requestPairing(candidateUrl: String): PairingRequest {
        val base = candidateUrl.trim().trimEnd('/')
        val payload = JSONObject().apply {
            put("device_id", deviceId)
            put("name", "${Build.MANUFACTURER} ${Build.MODEL}")
            put("sdk", Build.VERSION.SDK_INT)
        }
        val req = Request.Builder().url("$base/api/pairing/request")
            .post(payload.toString().toRequestBody("application/json".toMediaType())).build()
        client.newCall(req).execute().use { response ->
            val raw = response.body?.string().orEmpty()
            val root = JSONObject(raw.ifBlank { "{}" })
            if (!response.isSuccessful) throw IllegalStateException(root.optString("error", "Pairing request failed"))
            val requestId = root.optString("request_id")
            if (requestId.isBlank()) throw IllegalStateException("Pi did not return a pairing request ID")
            return PairingRequest(requestId, base)
        }
    }

    fun pollPairing(pairing: PairingRequest): PairingResult {
        val url = "${pairing.serverUrl}/api/pairing/status?request_id=${pairing.requestId}&device_id=$deviceId"
        val req = Request.Builder().url(url).get().build()
        client.newCall(req).execute().use { response ->
            val root = JSONObject(response.body?.string().orEmpty().ifBlank { "{}" })
            if (!response.isSuccessful) return PairingResult(root.optString("status", "waiting"))
            val status = root.optString("status", "waiting")
            val approvedToken = root.optString("device_token", "")
            if (status == "approved" && approvedToken.isNotBlank()) {
                prefs.edit()
                    .putString("server_url", pairing.serverUrl)
                    .putString("device_token", approvedToken)
                    .remove("token")
                    .apply()
                return PairingResult("approved", true)
            }
            return PairingResult(status)
        }
    }

    fun chat(message: String): ChatReply {
        if (!configured()) return ChatReply("Pair this phone with your Pi first.")
        val payload = JSONObject().put("message", message)
        val req = authorized(Request.Builder().url("$serverUrl/api/android/chat"))
            .post(payload.toString().toRequestBody("application/json".toMediaType())).build()
        client.newCall(req).execute().use { response ->
            val raw = response.body?.string().orEmpty()
            if (response.isSuccessful) {
                val root = JSONObject(raw)
                return ChatReply(root.optString("reply", "Sent."), root.optString("emotion", "neutral"), root.optString("gesture", "idle"))
            }
        }
        return ChatReply("The Pi chat endpoint is unavailable.")
    }

    fun sendVisionFrame(jpeg: ByteArray): String {
        if (!configured()) return "Pair this phone with your Pi first."
        val payload = JSONObject().apply {
            put("source", "android-camera")
            put("image_base64", Base64.encodeToString(jpeg, Base64.NO_WRAP))
        }
        val req = authorized(Request.Builder().url("$serverUrl/api/android/vision"))
            .post(payload.toString().toRequestBody("application/json".toMediaType())).build()
        client.newCall(req).execute().use { response ->
            val root = JSONObject(response.body?.string().orEmpty())
            if (!response.isSuccessful) throw IllegalStateException(root.optString("error", "Vision request failed"))
            val description = root.optString("description", "")
            if (description.isNotBlank()) return description
            val affect = root.optJSONObject("affect")
            return if (affect != null) "Tentative facial cue: ${affect.optString("label", "unknown")}" else "Frame received."
        }
    }

    fun avatarUrl(): String {
        if (!configured()) return ""
        val req = authorized(Request.Builder().url("$serverUrl/api/avatar/config")).get().build()
        client.newCall(req).execute().use { response ->
            if (!response.isSuccessful) return ""
            return JSONObject(response.body?.string().orEmpty()).optString("url", "")
        }
    }

    fun heartbeat() {
        if (!configured()) return
        val bm = context.getSystemService(Context.BATTERY_SERVICE) as BatteryManager
        val battery = bm.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY)
        val currentUa = bm.getIntProperty(BatteryManager.BATTERY_PROPERTY_CURRENT_NOW)
        val batteryIntent = context.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        val plugged = batteryIntent?.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0) ?: 0
        val temperatureTenths = batteryIntent?.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, -1) ?: -1
        val voltageMv = batteryIntent?.getIntExtra(BatteryManager.EXTRA_VOLTAGE, -1) ?: -1
        val am = context.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
        val mem = ActivityManager.MemoryInfo().also(am::getMemoryInfo)
        val stat = StatFs(Environment.getDataDirectory().absolutePath)
        val thermal = if (Build.VERSION.SDK_INT >= 29) context.getSystemService(PowerManager::class.java).currentThermalStatus else -1
        val payload = JSONObject().apply {
            put("device_id", deviceId); put("name", "${Build.MANUFACTURER} ${Build.MODEL}")
            put("telemetry", JSONObject().apply {
                put("battery_percent", battery); put("charging", plugged != 0); put("battery_current_ma", currentUa / 1000.0)
                put("battery_temperature_c", if (temperatureTenths >= 0) temperatureTenths / 10.0 else JSONObject.NULL)
                put("battery_voltage_mv", if (voltageMv >= 0) voltageMv else JSONObject.NULL); put("thermal_status", thermal)
                put("memory_available_mb", mem.availMem / 1024 / 1024); put("memory_total_mb", mem.totalMem / 1024 / 1024); put("low_memory", mem.lowMemory)
                put("storage_free_mb", stat.availableBytes / 1024 / 1024); put("storage_total_mb", stat.totalBytes / 1024 / 1024)
                put("sdk", Build.VERSION.SDK_INT); put("model", Build.MODEL)
            })
        }
        post("/api/android/heartbeat", payload)
    }

    fun sendNotification(app: String, title: String, text: String) {
        if (!configured()) return
        val includePreview = prefs.getBoolean("notification_preview", true)
        val payload = JSONObject().apply {
            put("device_id", deviceId)
            put("notification", JSONObject().apply { put("app", app.take(80)); put("title", title.take(160)); put("text", if (includePreview) text.take(500) else "New notification") })
        }
        post("/api/android/notification", payload)
    }

    fun longPoll(after: Int): List<JSONObject> {
        if (!configured()) return emptyList()
        val request = authorized(Request.Builder().url("$serverUrl/api/android/commands?device_id=${deviceId}&after=$after&wait=25")).get().build()
        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) return emptyList()
            val arr = JSONObject(response.body?.string().orEmpty()).optJSONArray("commands") ?: return emptyList()
            return (0 until arr.length()).map { arr.getJSONObject(it) }
        }
    }

    private fun authorized(builder: Request.Builder): Request.Builder = builder.header("X-Neko-Device-Token", token)

    private fun post(path: String, json: JSONObject) {
        val request = authorized(Request.Builder().url(serverUrl + path))
            .post(json.toString().toRequestBody("application/json".toMediaType())).build()
        client.newCall(request).execute().close()
    }
}
