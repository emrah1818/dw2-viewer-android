package app.dw2viewer

import android.annotation.SuppressLint
import android.content.Intent
import android.content.pm.ApplicationInfo
import android.net.Uri
import android.os.Bundle
import android.provider.OpenableColumns
import android.view.ViewGroup
import android.webkit.JavascriptInterface
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import androidx.activity.OnBackPressedCallback
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.webkit.WebViewAssetLoader
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.concurrent.Executors

class MainActivity : AppCompatActivity() {
    private lateinit var web: WebView
    private lateinit var py: PyBridge
    private val pool = Executors.newSingleThreadExecutor()
    private var pendingPick: Pair<String, String>? = null          // (callId, art)
    private var pendingSave: Pair<String, String>? = null          // (callId, quellpfad)
    private var imageUri: Uri? = null                               // Original-Image des Nutzers (zum Überschreiben)
    private var imagePath: String? = null                           // Arbeitskopie im App-Speicher

    private val pickFile = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        val (id, kind) = pendingPick ?: return@registerForActivityResult
        pendingPick = null
        if (uri == null) resolve(id, ok(JSONObject.NULL))
        else pool.execute { handlePicked(id, kind, uri) }
    }

    private val saveFile = registerForActivityResult(ActivityResultContracts.CreateDocument("application/octet-stream")) { uri ->
        val (id, source) = pendingSave ?: return@registerForActivityResult
        pendingSave = null
        if (uri == null) { resolve(id, ok(false)); return@registerForActivityResult }
        pool.execute {
            try {
                writeTo(uri, File(source), "w")
                py.call("delete_export", JSONArray().put(source).toString())
                resolve(id, ok(true))
            } catch (e: Exception) {
                resolve(id, error(e.message ?: e.javaClass.simpleName))
            }
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        py = PyBridge(this)
        py.configure()
        val viewerDir = File(filesDir, "viewer").apply { mkdirs() }
        val loader = WebViewAssetLoader.Builder()
            .addPathHandler("/assets/", WebViewAssetLoader.AssetsPathHandler(this))
            .addPathHandler("/viewer/", WebViewAssetLoader.InternalStoragePathHandler(this, viewerDir))
            .build()

        web = WebView(this)
        val root = FrameLayout(this).apply { setBackgroundColor(0xFF0F1929.toInt()) }
        root.addView(web, ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
        setContentView(root)
        // Ab targetSdk 35/36 zeichnet die App unter den Systemleisten: Abstände selbst setzen.
        ViewCompat.setOnApplyWindowInsetsListener(root) { v, insets ->
            val bars = insets.getInsets(
                WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout() or WindowInsetsCompat.Type.ime()
            )
            v.setPadding(bars.left, bars.top, bars.right, bars.bottom)
            insets
        }
        WindowCompat.getInsetsController(window, root).apply {
            isAppearanceLightStatusBars = false
            isAppearanceLightNavigationBars = false
        }

        if (applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE != 0) WebView.setWebContentsDebuggingEnabled(true)
        web.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            allowFileAccess = false
            allowContentAccess = false
        }
        web.setBackgroundColor(0xFF0F1929.toInt())
        web.webViewClient = object : WebViewClient() {
            override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? =
                loader.shouldInterceptRequest(request.url)

            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                if (request.url.host == WebViewAssetLoader.DEFAULT_DOMAIN) return false
                startActivity(Intent(Intent.ACTION_VIEW, request.url))
                return true
            }
        }
        web.addJavascriptInterface(Bridge(), "Android")
        web.loadUrl("https://${WebViewAssetLoader.DEFAULT_DOMAIN}/assets/www/index.html")

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                web.evaluateJavascript("(window.__back ? window.__back() : false)") { handled ->
                    if (handled != "true") finish()
                }
            }
        })
    }

    override fun onDestroy() {
        pool.shutdown()
        super.onDestroy()
    }

    private fun ok(data: Any?) = JSONObject().put("ok", true).put("data", data ?: JSONObject.NULL).toString()
    private fun error(message: String) = JSONObject().put("ok", false).put("error", message).toString()

    private fun resolve(id: String, json: String) {
        web.post { web.evaluateJavascript("window.__resolve(${JSONObject.quote(id)}, ${JSONObject.quote(json)})", null) }
    }

    private fun progress(text: String, percent: Int) {
        web.post { web.evaluateJavascript("window.__progress && window.__progress(${JSONObject.quote(text)}, $percent)", null) }
    }

    /** Datei in eine vom Nutzer gewählte Adresse schreiben (mit Fortschritt). */
    private fun writeTo(uri: Uri, file: File, mode: String) {
        val size = file.length()
        var copied = 0L
        contentResolver.openOutputStream(uri, mode)!!.use { out ->
            file.inputStream().use { input ->
                val buf = ByteArray(1 shl 20)
                while (true) {
                    val n = input.read(buf); if (n < 0) break
                    out.write(buf, 0, n); copied += n
                    if (size > (8L shl 20)) progress("Datei wird gespeichert …", (copied * 100 / size).toInt())
                }
            }
        }
    }

    /** Neues Image über das Original des Nutzers schreiben; die alte Arbeitskopie bleibt als Sicherung. */
    private fun overwriteOriginal(id: String, exported: String) {
        val uri = imageUri
        val path = imagePath
        if (uri == null || path == null) { resolve(id, error("Kein Original-Image bekannt. Bitte Image erneut öffnen.")); return }
        try {
            writeTo(uri, File(exported), "wt")
        } catch (e: Exception) {
            resolve(id, error("Das Original konnte nicht überschrieben werden (${e.message ?: "kein Schreibzugriff"}). Bitte „Neues Image exportieren“ verwenden."))
            return
        }
        progress("Image wird neu eingelesen …", -1)
        resolve(id, py.call("adopt_image", JSONArray().put(exported).put(path).toString()))
    }

    private fun query(uri: Uri, column: String): String? =
        contentResolver.query(uri, arrayOf(column), null, null, null)?.use {
            if (it.moveToFirst() && !it.isNull(0)) it.getString(0) else null
        }

    /** Kopiert die gewählte Datei in den App-Speicher und übergibt sie an Python. */
    private fun handlePicked(id: String, kind: String, uri: Uri) {
        try {
            val folder = File(filesDir, if (kind == "image") "images" else "imports").apply { mkdirs() }
            val name = (query(uri, OpenableColumns.DISPLAY_NAME) ?: "datei").replace(Regex("[^A-Za-z0-9._ -]"), "_")
            val size = query(uri, OpenableColumns.SIZE)?.toLongOrNull() ?: -1L
            if (kind == "image") folder.listFiles()?.forEach { it.delete() }   // nur ein Image gleichzeitig
            if (size > 0 && folder.usableSpace < size + (64L shl 20)) {
                resolve(id, error("Zu wenig Speicherplatz: ${size shr 20} MB nötig, ${folder.usableSpace shr 20} MB frei."))
                return
            }
            val target = File(folder, name)
            var copied = 0L
            var last = -1
            contentResolver.openInputStream(uri)!!.use { input ->
                target.outputStream().use { output ->
                    val buffer = ByteArray(1 shl 20)
                    while (true) {
                        val n = input.read(buffer); if (n < 0) break
                        output.write(buffer, 0, n); copied += n
                        if (size > 0) {
                            val pct = (copied * 100 / size).toInt()
                            if (pct != last) { last = pct; progress("Datei wird übernommen …", pct) }
                        }
                    }
                }
            }
            if (kind == "image") {
                imageUri = uri
                imagePath = target.absolutePath
                try {
                    contentResolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
                } catch (_: Exception) { /* Schreibrecht nicht dauerhaft – Überschreiben meldet das */ }
            }
            if (kind == "file") {
                resolve(id, ok(JSONObject().put("path", target.absolutePath).put("name", name)))
                return
            }
            val method = when (kind) { "image" -> "open_image"; "roster" -> "roster_open"; else -> "load_project" }
            progress(if (kind == "image") "Image wird analysiert …" else "Datei wird gelesen …", -1)
            resolve(id, py.call(method, JSONArray().put(target.absolutePath).toString()))
        } catch (e: Throwable) {
            resolve(id, error(e.message ?: e.javaClass.simpleName))
        }
    }

    inner class Bridge {
        /** Aufruf aus der Oberfläche; Antwort kommt asynchron über window.__resolve. */
        @JavascriptInterface
        fun invoke(id: String, method: String, argsJson: String) {
            when (method) {
                "overwrite_original" -> {
                    val exported = JSONArray(argsJson).getString(0)
                    pool.execute { overwriteOriginal(id, exported) }
                }
                "pick_image", "pick_roster", "pick_project", "pick_file" -> runOnUiThread {
                    pendingPick = id to method.removePrefix("pick_")
                    pickFile.launch(arrayOf("*/*"))
                }
                "save_export" -> {
                    val a = JSONArray(argsJson)
                    runOnUiThread { pendingSave = id to a.getString(0); saveFile.launch(a.getString(1)) }
                }
                "app_info" -> resolve(id, ok(JSONObject()
                    .put("version", packageManager.getPackageInfo(packageName, 0).versionName)
                    .put("free_mb", filesDir.usableSpace shr 20)))
                else -> pool.execute {
                    try { resolve(id, py.call(method, argsJson)) }
                    catch (t: Throwable) { resolve(id, error(t.message ?: t.javaClass.simpleName)) }
                }
            }
        }
    }
}
