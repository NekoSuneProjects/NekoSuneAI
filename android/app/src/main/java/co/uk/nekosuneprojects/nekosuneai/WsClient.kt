package co.uk.nekosuneprojects.nekosuneai

import android.util.Log
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Persistent link to the NekoSuneAI backend, with HTTP as the fallback.
 *
 * A chat turn runs the whole backend pipeline -- web search, the LLM, TTS --
 * and regularly outlives a reverse proxy's *read* timeout, which answers this
 * app 504 and throws away a reply the backend had already finished. A proxy
 * applies its far longer *idle* timeout to an upgraded connection, and OkHttp's
 * ping interval below stops even that firing, so a turn can take as long as it
 * takes. It also lets the backend push to this phone rather than being asked.
 *
 * The address is derived from the backend address already configured for HTTP
 * -- `https://host` becomes `wss://host/wss` -- so there is one setting, not
 * two that can drift apart.
 *
 * Nothing is replaced. [ApiClient] keeps every HTTP path and falls back the
 * moment the socket is unavailable, which is why [request] fails fast instead
 * of waiting to reconnect: making the owner wait on a transport detail is
 * worse than just using the other one.
 */
class WsClient(
    private val serverUrl: () -> String,
    private val deviceId: () -> String,
    private val token: () -> String,
    private val onPush: (JSONObject) -> Unit = {},
) {
    private companion object {
        const val TAG = "NekoWs"

        /** Comfortably inside the 60s a proxy usually allows an idle upgrade. */
        const val PING_SECONDS = 20L

        /** Only bounds a reply that never arrives; a real turn can take minutes. */
        const val REQUEST_TIMEOUT_SECONDS = 300L
        const val RECONNECT_MIN_MS = 2_000L
        const val RECONNECT_MAX_MS = 60_000L
    }

    private val client = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        // OkHttp sends the pings; without them a proxy eventually drops the
        // connection as idle, which is the thing this class exists to avoid.
        .pingInterval(PING_SECONDS, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.SECONDS)   // a socket has no per-read deadline
        .build()

    private val pending = ConcurrentHashMap<String, Waiter>()
    private val authenticated = AtomicBoolean(false)
    private val stopped = AtomicBoolean(false)
    private var socket: WebSocket? = null
    private var reconnectDelay = RECONNECT_MIN_MS

    @Volatile
    var lastError: String = ""
        private set

    val connected: Boolean get() = authenticated.get() && socket != null

    private class Waiter {
        val latch = CountDownLatch(1)
        @Volatile var result: JSONObject? = null
    }

    /** `https://host/base` -> `wss://host/base/wss`, or "" when unusable. */
    fun socketUrl(): String {
        val base = serverUrl().trim().trimEnd('/')
        if (base.isBlank()) return ""
        return when {
            base.startsWith("https://") -> "wss://" + base.removePrefix("https://") + "/wss"
            base.startsWith("http://") -> "ws://" + base.removePrefix("http://") + "/wss"
            else -> ""
        }
    }

    fun start() {
        if (stopped.get()) return
        val url = socketUrl()
        if (url.isBlank() || token().isBlank()) {
            // Unpaired or unconfigured: nothing to authenticate with, so there
            // is no point burning reconnect attempts that would only be refused.
            return
        }
        val request = Request.Builder().url(url).build()
        socket = client.newWebSocket(request, Listener())
    }

    fun stop() {
        stopped.set(true)
        authenticated.set(false)
        socket?.close(1000, "client stopping")
        socket = null
        failAllPending("the connection was closed")
    }

    /**
     * Send a message and wait for its correlated answer.
     *
     * Throws when the socket is not usable, which is the caller's signal to
     * take its HTTP path instead.
     */
    fun request(message: JSONObject, timeoutSeconds: Long = REQUEST_TIMEOUT_SECONDS): JSONObject {
        val live = socket
        if (!connected || live == null) throw IllegalStateException("not connected")

        val id = UUID.randomUUID().toString()
        val waiter = Waiter()
        pending[id] = waiter
        try {
            if (!live.send(message.put("id", id).toString())) {
                throw IllegalStateException("the message could not be queued")
            }
            if (!waiter.latch.await(timeoutSeconds, TimeUnit.SECONDS)) {
                throw IllegalStateException("timed out waiting for the backend to answer")
            }
        } finally {
            pending.remove(id)
        }

        val result = waiter.result ?: throw IllegalStateException("the connection dropped")
        if (result.optString("type") == "error") {
            throw IllegalStateException(result.optString("error", "the backend reported an error"))
        }
        return result
    }

    /** Fire-and-forget. False when there is no usable connection. */
    fun send(message: JSONObject): Boolean {
        val live = socket
        if (!connected || live == null) return false
        return live.send(message.toString())
    }

    private fun failAllPending(reason: String) {
        // Waiting callers must be released to their HTTP fallback rather than
        // left blocked until their own timeout.
        val failure = JSONObject().put("type", "error").put("error", reason)
        pending.values.forEach { waiter ->
            waiter.result = failure
            waiter.latch.countDown()
        }
        pending.clear()
    }

    private fun scheduleReconnect() {
        if (stopped.get()) return
        val delay = reconnectDelay
        reconnectDelay = (reconnectDelay * 2).coerceAtMost(RECONNECT_MAX_MS)
        Thread {
            try {
                Thread.sleep(delay)
            } catch (interrupted: InterruptedException) {
                return@Thread
            }
            if (!stopped.get()) start()
        }.apply { isDaemon = true }.start()
    }

    private inner class Listener : WebSocketListener() {
        override fun onOpen(webSocket: WebSocket, response: Response) {
            socket = webSocket
            // The device token, checked by the backend exactly as the HTTP
            // routes check it. A socket is not a softer door than a request.
            webSocket.send(
                JSONObject()
                    .put("type", "auth")
                    .put("device_id", deviceId())
                    .put("token", token())
                    .toString()
            )
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            val message = try {
                JSONObject(text)
            } catch (invalid: Exception) {
                return
            }
            when (message.optString("type")) {
                "auth.ok" -> {
                    authenticated.set(true)
                    reconnectDelay = RECONNECT_MIN_MS
                    lastError = ""
                    Log.i(TAG, "live link established")
                    return
                }
                "auth.error" -> {
                    authenticated.set(false)
                    lastError = message.optString("error", "unauthorized")
                    Log.w(TAG, "live link refused: $lastError")
                    return
                }
                "pong" -> return
                "command", "notify" -> {
                    onPush(message)
                    return
                }
            }

            val id = message.optString("id")
            if (id.isBlank()) return
            pending[id]?.let { waiter ->
                waiter.result = message
                waiter.latch.countDown()
            }
        }

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
            // The usual cause is a proxy that will not forward an upgrade, so
            // record what it actually said rather than a generic failure.
            lastError = response?.let { "HTTP ${it.code}" } ?: (t.message ?: "connection failed")
            Log.w(TAG, "live link lost: $lastError")
            authenticated.set(false)
            socket = null
            failAllPending("the connection dropped")
            scheduleReconnect()
        }

        override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
            authenticated.set(false)
            socket = null
            failAllPending("the connection closed")
            if (code != 1000) scheduleReconnect()
        }
    }
}
