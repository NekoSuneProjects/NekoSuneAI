package co.uk.nekosuneprojects.nekosuneai

import android.telecom.Call
import android.telecom.CallScreeningService
import androidx.work.Data
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager

class ScamCallScreeningService : CallScreeningService() {
    override fun onScreenCall(callDetails: Call.Details) {
        if (callDetails.callDirection == Call.Details.DIRECTION_INCOMING) {
            val number = callDetails.handle?.schemeSpecificPart.orEmpty().trim()
            if (number.isNotBlank()) enqueueLookup(number)
        }

        // Never make the caller wait for a web lookup. Android requires a fast
        // CallScreeningService response; WorkManager continues delivery after
        // this service callback has finished or the process is reclaimed.
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
    }

    private fun enqueueLookup(number: String) {
        val request = OneTimeWorkRequestBuilder<ScamCallLookupWorker>()
            .setInputData(Data.Builder().putString(ScamCallLookupWorker.KEY_NUMBER, number).build())
            .build()
        WorkManager.getInstance(applicationContext).enqueueUniqueWork(
            "neko-call-${number.hashCode()}-${System.currentTimeMillis() / 5000L}",
            ExistingWorkPolicy.KEEP,
            request
        )
    }
}
