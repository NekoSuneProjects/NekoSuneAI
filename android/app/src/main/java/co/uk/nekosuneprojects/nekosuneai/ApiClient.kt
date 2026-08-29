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

class ApiClient(private val context: Context) {
    private val prefs = context.getSharedPreferences("neko", Context.MODE_PRIVATE)
    private val client = OkHttpClient.Builder().connectTimeout(10, TimeUnit.SECONDS).readTimeout(90, TimeUnit.SECONDS).build()

    val deviceId: String
        get() = prefs.getString("device_id", null) ?: UUID.randomUUID().toString().also { prefs.edit().putString("device_id", it).apply() }

    private val baseUrl: String get() = (prefs.getString("server_url", "") ?: "").trimEnd('/')
    private val token: String get() = prefs.getString("token", "") ?: ""

    fun configured(): Boolean = baseUrl.startsWith("http") && token.isNotBlank()
    fun save(server: String, authToken: String) { prefs.edit().putString("server_url", server.trim().trimEnd('/')).putString("token", authToken.trim()).apply() }

    fun chat(message: String): ChatReply {
        if (!configured()) return ChatReply("Connect this phone to your Pi first.")
        val payload = JSONObject().put("message", message)
        val req = Request.Builder().url("$baseUrl/api/android/chat").header("X-Neko-Token", token)
            .post(payload.toString().toRequestBody("application/json".toMediaType())).build()
        client.newCall(req).execute().use { response ->
            val raw = response.body?.string().orEmpty()
            if (response.isSuccessful) {
                val root = JSONObject(raw)
                return ChatReply(root.optString("reply", "Sent."), root.optString("emotion", "neutral"), root.optString("gesture", "idle"))
            }
        }
        return ChatReply("The Pi chat endpoint is unavailable. Update the Pi smart-speaker branch first.")
    }

    fun sendVisionFrame(jpeg: ByteArray): String {
        if (!configured()) return "Connect this phone to your Pi first."
        val payload = JSONObject().apply {
            put("source", "android-camera")
            put("image_base64", Base64.encodeToString(jpeg, Base64.NO_WRAP))
        }
        val req = Request.Builder().url("$baseUrl/api/android/vision").header("X-Neko-Token", token)
            .post(payload.toString().toRequestBody("application/json".toMediaType())).build()
        client.newCall(req).execute().use { response ->
            val root = JSONObject(response.body?.string().orEmpty())
            if (!response.isSuccessful) throw IllegalStateException(root.optString("error", "Vision request failed"))
            return root.optString("description", "")
        }
    }

    fun avatarUrl(): String {
        if (!configured()) return ""
        val req = Request.Builder().url("$baseUrl/api/avatar/config").header("X-Neko-Token", token).get().build()
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
        val request = Request.Builder().url("$baseUrl/api/android/commands?device_id=${deviceId}&after=$after&wait=25").header("X-Neko-Token", token).get().build()
        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) return emptyList()
            val arr = JSONObject(response.body?.string().orEmpty()).optJSONArray("commands") ?: return emptyList()
            return (0 until arr.length()).map { arr.getJSONObject(it) }
        }
    }

    private fun post(path: String, json: JSONObject) {
        val request = Request.Builder().url(baseUrl + path).header("X-Neko-Token", token).post(json.toString().toRequestBody("application/json".toMediaType())).build()
        client.newCall(request).execute().close()
    }
}
