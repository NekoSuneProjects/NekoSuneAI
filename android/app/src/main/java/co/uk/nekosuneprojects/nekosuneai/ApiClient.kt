package co.uk.nekosuneprojects.nekosuneai

import android.content.Context
import android.os.Build
import android.os.BatteryManager
import android.app.ActivityManager
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.util.UUID
import java.util.concurrent.TimeUnit

class ApiClient(private val context: Context) {
    private val prefs = context.getSharedPreferences("neko", Context.MODE_PRIVATE)
    private val client = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(35, TimeUnit.SECONDS)
        .build()

    val deviceId: String
        get() = prefs.getString("device_id", null) ?: UUID.randomUUID().toString().also {
            prefs.edit().putString("device_id", it).apply()
        }

    private val baseUrl: String get() = (prefs.getString("server_url", "") ?: "").trimEnd('/')
    private val token: String get() = prefs.getString("token", "") ?: ""

    fun configured(): Boolean = baseUrl.startsWith("http") && token.isNotBlank()

    fun save(server: String, authToken: String) {
        prefs.edit().putString("server_url", server.trim().trimEnd('/')).putString("token", authToken.trim()).apply()
    }

    fun heartbeat() {
        if (!configured()) return
        val bm = context.getSystemService(Context.BATTERY_SERVICE) as BatteryManager
        val battery = bm.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY)
        val currentUa = bm.getIntProperty(BatteryManager.BATTERY_PROPERTY_CURRENT_NOW)
        val am = context.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
        val mem = ActivityManager.MemoryInfo().also(am::getMemoryInfo)
        val payload = JSONObject().apply {
            put("device_id", deviceId)
            put("name", "${Build.MANUFACTURER} ${Build.MODEL}")
            put("telemetry", JSONObject().apply {
                put("battery_percent", battery)
                put("charging", currentUa > 0)
                put("battery_current_ma", currentUa / 1000.0)
                put("memory_available_mb", mem.availMem / 1024 / 1024)
                put("memory_total_mb", mem.totalMem / 1024 / 1024)
                put("low_memory", mem.lowMemory)
                put("sdk", Build.VERSION.SDK_INT)
                put("model", Build.MODEL)
            })
        }
        post("/api/android/heartbeat", payload)
    }

    fun sendNotification(app: String, title: String, text: String) {
        if (!configured()) return
        val includePreview = prefs.getBoolean("notification_preview", true)
        val payload = JSONObject().apply {
            put("device_id", deviceId)
            put("notification", JSONObject().apply {
                put("app", app.take(80))
                put("title", title.take(160))
                put("text", if (includePreview) text.take(500) else "New notification")
            })
        }
        post("/api/android/notification", payload)
    }

    fun longPoll(after: Int): List<JSONObject> {
        if (!configured()) return emptyList()
        val url = "$baseUrl/api/android/commands?device_id=${deviceId}&after=$after&wait=25"
        val request = Request.Builder().url(url).header("X-Neko-Token", token).get().build()
        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) return emptyList()
            val root = JSONObject(response.body?.string().orEmpty())
            val arr = root.optJSONArray("commands") ?: return emptyList()
            return (0 until arr.length()).map { arr.getJSONObject(it) }
        }
    }

    private fun post(path: String, json: JSONObject) {
        val body = json.toString().toRequestBody("application/json".toMediaType())
        val request = Request.Builder().url(baseUrl + path).header("X-Neko-Token", token).post(body).build()
        client.newCall(request).execute().close()
    }
}
