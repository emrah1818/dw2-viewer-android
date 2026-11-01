package app.dw2viewer

import android.content.Context
import com.chaquo.python.Python
import java.io.File

/** Einziger Zugang zu Python: call(methode, jsonArgumente) -> JSON-Text. */
class PyBridge(private val context: Context) {
    private val module by lazy { Python.getInstance().getModule("android_api") }

    fun configure() {
        module.callAttr(
            "configure",
            context.filesDir.absolutePath,
            context.applicationInfo.nativeLibraryDir,
            File(context.filesDir, "data").absolutePath,
        )
    }

    fun call(method: String, argsJson: String): String =
        module.callAttr("call", method, argsJson).toString()
}
