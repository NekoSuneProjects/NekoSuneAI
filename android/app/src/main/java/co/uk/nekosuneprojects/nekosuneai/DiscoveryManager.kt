package co.uk.nekosuneprojects.nekosuneai

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
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
                onStatus("Searching your local network for NekoSuneAI…")
            }

            override fun onServiceFound(serviceInfo: NsdServiceInfo) {
                if (!serviceInfo.serviceType.contains("_nekosuneai._tcp")) return
                try {
                    nsd.resolveService(serviceInfo, object : NsdManager.ResolveListener {
                        override fun onResolveFailed(serviceInfo: NsdServiceInfo, errorCode: Int) = Unit
                        override fun onServiceResolved(resolved: NsdServiceInfo) {
                            val host = resolved.host?.hostAddress ?: return
                            val urlHost = if (host.contains(':')) "[$host]" else host
                            onFound("http://$urlHost:${resolved.port}", resolved.serviceName)
                        }
                    })
                } catch (_: Exception) {
                }
            }

            override fun onServiceLost(serviceInfo: NsdServiceInfo) = Unit
            override fun onDiscoveryStopped(serviceType: String) { running.set(false) }
            override fun onStartDiscoveryFailed(serviceType: String, errorCode: Int) {
                running.set(false)
                onStatus("Automatic discovery could not start. You can still use Advanced connection settings.")
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

    fun stop() {
        val current = listener ?: return
        listener = null
        if (running.getAndSet(false)) {
            try { nsd.stopServiceDiscovery(current) } catch (_: Exception) {}
        }
    }
}
