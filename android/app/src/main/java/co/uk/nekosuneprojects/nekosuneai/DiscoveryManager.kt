package co.uk.nekosuneprojects.nekosuneai

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.os.Build
import java.nio.charset.StandardCharsets
import java.util.concurrent.atomic.AtomicBoolean

class DiscoveryManager(context: Context) {
    private val nsd = context.getSystemService(Context.NSD_SERVICE) as NsdManager
    private val running = AtomicBoolean(false)
    private var listener: NsdManager.DiscoveryListener? = null

    fun discover(onFound: (String, String) -> Unit, onStatus: (String) -> Unit) {
        stop()
        val discovery = object : NsdManager.DiscoveryListener {
            override fun onDiscoveryStarted(serviceType: String) {
                running.set(true)
                onStatus("Searching local network for NekoSuneAI HTTPS/domain or IPv4 server…")
            }

            override fun onServiceFound(serviceInfo: NsdServiceInfo) {
                if (!serviceInfo.serviceType.contains("_nekosuneai._tcp")) return
                try {
                    nsd.resolveService(serviceInfo, object : NsdManager.ResolveListener {
                        override fun onResolveFailed(serviceInfo: NsdServiceInfo, errorCode: Int) = Unit

                        override fun onServiceResolved(resolved: NsdServiceInfo) {
                            val localHost = resolved.host?.hostAddress ?: return
                            val urlHost = if (localHost.contains(':')) "[$localHost]" else localHost
                            val localUrl = "http://$urlHost:${resolved.port}"
                            val publicUrl = advertisedValue(resolved, "public_url")
                                ?.trim()
                                ?.trimEnd('/')
                                ?.takeIf { it.startsWith("https://", ignoreCase = true) }

                            // If the Docker server advertises its public HTTPS origin,
                            // pair through that domain so the saved connection works on
                            // Wi-Fi and mobile data. If no domain is configured, keep the
                            // direct local IPv4:8788 endpoint as the fallback.
                            onFound(publicUrl ?: localUrl, resolved.serviceName)
                        }
                    })
                } catch (_: Exception) {
                }
            }

            override fun onServiceLost(serviceInfo: NsdServiceInfo) = Unit
            override fun onDiscoveryStopped(serviceType: String) { running.set(false) }
            override fun onStartDiscoveryFailed(serviceType: String, errorCode: Int) {
                running.set(false)
                onStatus("Automatic discovery could not start. You can still enter the HTTPS domain or local IPv4 address manually.")
                try { nsd.stopServiceDiscovery(this) } catch (_: Exception) {}
            }
            override fun onStopDiscoveryFailed(serviceType: String, errorCode: Int) {
                running.set(false)
            }
        }
        listener = discovery
        try {
            nsd.discoverServices("_nekosuneai._tcp.", NsdManager.PROTOCOL_DNS_SD, discovery)
        } catch (_: Exception) {
            onStatus("Automatic discovery is unavailable on this network.")
        }
    }

    private fun advertisedValue(info: NsdServiceInfo, key: String): String? {
        return try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
                val raw = info.attributes[key] ?: return null
                String(raw, StandardCharsets.UTF_8)
            } else null
        } catch (_: Exception) {
            null
        }
    }

    fun stop() {
        val current = listener ?: return
        listener = null
        if (running.getAndSet(false)) {
            try { nsd.stopServiceDiscovery(current) } catch (_: Exception) {}
        }
    }
}
