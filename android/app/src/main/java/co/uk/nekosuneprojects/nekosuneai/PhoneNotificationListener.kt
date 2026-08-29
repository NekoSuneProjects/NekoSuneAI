package co.uk.nekosuneprojects.nekosuneai

import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import kotlin.concurrent.thread

class PhoneNotificationListener : NotificationListenerService() {
    override fun onNotificationPosted(sbn: StatusBarNotification?) {
        val item = sbn ?: return
        if (item.packageName == packageName) return
        val n = item.notification
        val extras = n.extras
        val title = extras.getCharSequence("android.title")?.toString().orEmpty()
        val text = extras.getCharSequence("android.text")?.toString().orEmpty()
        if (title.isBlank() && text.isBlank()) return
        val appName = try {
            val info = packageManager.getApplicationInfo(item.packageName, 0)
            packageManager.getApplicationLabel(info).toString()
        } catch (_: Exception) { item.packageName }

        // No permanent worker is created for notifications: send only when the
        // OS already woke this listener for a real notification event.
        thread(name = "NekoNotice", isDaemon = true) {
            try { ApiClient(this).sendNotification(appName, title, text) } catch (_: Exception) {}
        }
    }
}
