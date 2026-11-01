package app.dw2viewer

import android.app.Application
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import java.io.File

class App : Application() {
    override fun onCreate() {
        super.onCreate()
        if (!Python.isStarted()) Python.start(AndroidPlatform(this))
        copyAssetData()
    }

    /** Kopiert die kleinen JSON-Tabellen (Namen, Datei-IDs) in einen echten Ordner für Python. */
    private fun copyAssetData() {
        val target = File(filesDir, "data").apply { mkdirs() }
        assets.list("data")?.forEach { name ->
            val out = File(target, name)
            val bytes = assets.open("data/$name").use { it.readBytes() }
            if (!out.exists() || !out.readBytes().contentEquals(bytes)) out.writeBytes(bytes)
        }
    }
}
