package co.uk.nekosuneprojects.nekosuneai

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationCompat
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.concurrent.thread

class NtfySubscriber(private val context: Context) {
    private val prefs = context.getSharedPreferences("neko", Context.MODE_PRIVATE)
    private val running = AtomicBoolean(false)
    private val client = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.SECONDS)
        .build()

    fun start() {
        if (!running.compareAndSet(false, true)) return
        ensureChannel()
        thread(name = "NekoNtfy", isDaemon = true) { loop() }
    }

    fun stop() {
        running.set(false)
        client.dispatcher.cancelAll()
    }

    private fun loop() {
        while (running.get()) {
            try {
                val cfg = fetchConfig()
                if (cfg == null || !cfg.enabled) {
                    sleepQuiet(60_000)
                    continue
                }
                stream(cfg)
            } catch (_: Exception) {
                sleepQuiet(10_000)
            }
        }
    }

    private fun fetchConfig(): Config? {
        val server = prefs.getString("server_url", "").orEmpty().trim().trimEnd('/')
        val deviceToken = prefs.getString("device_token", "").orEmpty()
        val legacyToken = prefs.getString("token", "").orEmpty()
        if (!server.startsWith("http") || (deviceToken.isBlank() && legacyToken.isBlank())) return null

        val builder = Request.Builder().url("$server/api/android/ntfy-config")
        if (deviceToken.isNotBlank()) builder.header("X-Neko-Device-Token", deviceToken)
        else builder.header("X-Neko-Token", legacyToken)
        client.newCall(builder.get().build()).execute().use { response ->
            if (!response.isSuccessful) return null
            val root = JSONObject(response.body?.string().orEmpty().ifBlank { "{}" })
            val url = root.optString("url", "").trim().trimEnd('/')
            val topic = root.optString("topic", "").trim()
            val enabled = root.optBoolean("enabled", false) && url.startsWith("https://") && topic.isNotBlank()
            return Config(enabled, url, topic, root.optString("token", ""))
        }
    }

    private fun stream(cfg: Config) {
        val builder = Request.Builder()
            .url("${cfg.url}/${cfg.topic}/json?since=10m")
            .header("Accept", "application/x-ndjson")
        if (cfg.token.isNotBlank()) builder.header("Authorization", "Bearer ${cfg.token}")

        client.newCall(builder.get().build()).execute().use { response ->
            if (!response.isSuccessful) throw IllegalStateException("ntfy HTTP ${response.code}")
            val source = response.body?.source() ?: return
            while (running.get() && !source.exhausted()) {
                val line = source.readUtf8Line() ?: break
                if (line.isBlank()) continue
                val item = try { JSONObject(line) } catch (_: Exception) { continue }
                if (item.optString("event") != "message") continue
                show(item)
            }
        }
    }

    private fun show(item: JSONObject) {
        val title = item.optString("title", "NekoSuneAI").ifBlank { "NekoSuneAI" }
        val message = item.optString("message", "").trim()
        if (message.isBlank()) return
        val priority = item.optInt("priority", 3)
        val open = PendingIntent.getActivity(
            context,
            item.optString("id", message).hashCode(),
            Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val notification = NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle(title)
            .setContentText(message)
            .setStyle(NotificationCompat.BigTextStyle().bigText(message))
            .setContentIntent(open)
            .setAutoCancel(true)
            .setPriority(if (priority >= 5) NotificationCompat.PRIORITY_MAX else if (priority >= 4) NotificationCompat.PRIORITY_HIGH else NotificationCompat.PRIORITY_DEFAULT)
            .build()
        context.getSystemService(NotificationManager::class.java).notify(item.optString("id", message).hashCode(), notification)
    }

    private fun ensureChannel() {
        val nm = context.getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CHANNEL_ID, "NekoSuneAI Alerts", NotificationManager.IMPORTANCE_HIGH).apply {
            description = "Alerts delivered from the paired NekoSuneAI ntfy server"
            enableVibration(true)
        })
    }

    private fun sleepQuiet(ms: Long) {
        try { Thread.sleep(ms) } catch (_: InterruptedException) { running.set(false) }
    }

    private data class Config(val enabled: Boolean, val url: String, val topic: String, val token: String)

    companion object {
        private const val CHANNEL_ID = "neko_ntfy_alerts"
    }
}
