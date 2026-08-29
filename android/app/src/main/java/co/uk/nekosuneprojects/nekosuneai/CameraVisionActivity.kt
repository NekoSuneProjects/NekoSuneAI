package co.uk.nekosuneprojects.nekosuneai

import android.Manifest
import android.graphics.Color
import android.graphics.ImageFormat
import android.graphics.Rect
import android.graphics.Typeface
import android.graphics.YuvImage
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.view.Gravity
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.core.content.ContextCompat
import java.io.ByteArrayOutputStream
import java.util.concurrent.Executors
import kotlin.concurrent.thread

class CameraVisionActivity : AppCompatActivity() {
    private lateinit var api: ApiClient
    private lateinit var previewView: PreviewView
    private lateinit var status: TextView
    private val cameraExecutor = Executors.newSingleThreadExecutor()
    @Volatile private var lastSentAt = 0L
    @Volatile private var uploadBusy = false

    private val bg = Color.parseColor("#080914")
    private val surface = Color.parseColor("#111329")
    private val border = Color.parseColor("#292D55")
    private val textColor = Color.parseColor("#F4F2FF")
    private val muted = Color.parseColor("#B3B7DC")
    private val violet = Color.parseColor("#A78BFA")
    private val cyan = Color.parseColor("#67E8F9")

    private val askCamera = registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) startCamera() else status.text = "Camera permission was not granted. Nothing is being shared."
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.statusBarColor = bg
        window.navigationBarColor = bg
        api = ApiClient(this)

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(16), dp(18), dp(16), dp(24))
            setBackgroundColor(bg)
        }
        root.addView(TextView(this).apply {
            text = "VISION"
            textSize = 10f
            letterSpacing = .13f
            typeface = Typeface.DEFAULT_BOLD
            setTextColor(violet)
        })
        root.addView(TextView(this).apply {
            text = "Phone Camera"
            textSize = 24f
            typeface = Typeface.DEFAULT_BOLD
            setTextColor(textColor)
            setPadding(0, dp(4), 0, dp(3))
        })
        root.addView(TextView(this).apply {
            text = "Foreground-only camera sharing to your paired NekoSuneAI server."
            textSize = 13f
            setTextColor(muted)
        })

        status = TextView(this).apply {
            text = "● Camera sharing is OFF"
            textSize = 13f
            setTextColor(cyan)
            setPadding(dp(12), dp(9), dp(12), dp(9))
            background = rounded(Color.parseColor("#17213A"), Color.parseColor("#345D77"), 12)
        }
        root.addView(status, params(top = 14))

        previewView = PreviewView(this).apply {
            scaleType = PreviewView.ScaleType.FILL_CENTER
            background = rounded(surface, border, 16)
        }
        root.addView(previewView, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f).apply {
            topMargin = dp(12)
            bottomMargin = dp(12)
        })

        root.addView(Button(this).apply {
            text = "Stop sharing camera"
            isAllCaps = false
            textSize = 14f
            typeface = Typeface.DEFAULT_BOLD
            setTextColor(Color.parseColor("#111329"))
            background = rounded(violet, cyan, 12)
            gravity = Gravity.CENTER
            setOnClickListener { finish() }
        })
        root.addView(TextView(this).apply {
            text = "The camera closes immediately when you leave this screen. Raw frames are not intentionally saved by the companion vision endpoint."
            textSize = 11f
            setTextColor(muted)
            setPadding(0, dp(10), 0, 0)
        })

        setContentView(root)
        askCamera.launch(Manifest.permission.CAMERA)
    }

    private fun startCamera() {
        if (!api.configured()) { status.text = "● Pair the app to your Pi first."; return }
        val providerFuture = ProcessCameraProvider.getInstance(this)
        providerFuture.addListener({
            val provider = providerFuture.get()
            val preview = Preview.Builder().build().also { it.setSurfaceProvider(previewView.surfaceProvider) }
            val analysis = ImageAnalysis.Builder()
                .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                .setTargetResolution(android.util.Size(640, 480))
                .build()
            analysis.setAnalyzer(cameraExecutor) { image -> analyseFrame(image) }
            try {
                provider.unbindAll()
                provider.bindToLifecycle(this, CameraSelector.DEFAULT_FRONT_CAMERA, preview, analysis)
                status.text = "● Camera sharing ACTIVE — one frame about every 5 seconds"
            } catch (e: Exception) {
                status.text = "● Could not start camera: ${e.message}"
            }
        }, ContextCompat.getMainExecutor(this))
    }

    private fun analyseFrame(image: ImageProxy) {
        val now = System.currentTimeMillis()
        if (uploadBusy || now - lastSentAt < 5000) { image.close(); return }
        val jpeg = try { imageToJpeg(image) } catch (_: Exception) { null } finally { image.close() }
        if (jpeg == null || jpeg.size > 1_200_000) return
        lastSentAt = now
        uploadBusy = true
        thread(name = "NekoCameraVision") {
            try {
                val description = api.sendVisionFrame(jpeg)
                runOnUiThread { if (!isFinishing) status.text = "● Camera ACTIVE\nNeko sees: ${description.take(220)}" }
            } catch (e: Exception) {
                runOnUiThread { if (!isFinishing) status.text = "● Camera ACTIVE — vision error: ${e.message}" }
            } finally { uploadBusy = false }
        }
    }

    private fun imageToJpeg(image: ImageProxy): ByteArray {
        val width = image.width; val height = image.height
        val y = image.planes[0]; val u = image.planes[1]; val v = image.planes[2]
        val nv21 = ByteArray(width * height * 3 / 2)
        copyPlane(y, width, height, nv21, 0, 1)
        val chromaOffset = width * height
        copyChroma(v, width / 2, height / 2, nv21, chromaOffset, 2)
        copyChroma(u, width / 2, height / 2, nv21, chromaOffset + 1, 2)
        val out = ByteArrayOutputStream()
        YuvImage(nv21, ImageFormat.NV21, width, height, null).compressToJpeg(Rect(0, 0, width, height), 58, out)
        return out.toByteArray()
    }

    private fun copyPlane(plane: ImageProxy.PlaneProxy, width: Int, height: Int, out: ByteArray, offset: Int, step: Int) {
        val buffer = plane.buffer.duplicate(); val rowStride = plane.rowStride; val pixelStride = plane.pixelStride
        var dst = offset
        for (row in 0 until height) for (col in 0 until width) {
            val index = row * rowStride + col * pixelStride
            if (index < buffer.limit() && dst < out.size) out[dst] = buffer.get(index)
            dst += step
        }
    }

    private fun copyChroma(plane: ImageProxy.PlaneProxy, width: Int, height: Int, out: ByteArray, offset: Int, step: Int) {
        copyPlane(plane, width, height, out, offset, step)
    }

    private fun rounded(fill: Int, stroke: Int, radiusDp: Int) = GradientDrawable().apply {
        shape = GradientDrawable.RECTANGLE
        setColor(fill)
        cornerRadius = dp(radiusDp).toFloat()
        setStroke(dp(1), stroke)
    }

    private fun params(top: Int = 0) = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply {
        topMargin = dp(top)
    }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()

    override fun onDestroy() { cameraExecutor.shutdownNow(); super.onDestroy() }
}
