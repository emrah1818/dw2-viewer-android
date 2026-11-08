plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

android {
    namespace = "app.dw2viewer"
    compileSdk = 36

    defaultConfig {
        applicationId = "app.dw2viewer.studio"
        minSdk = 24
        targetSdk = 36
        versionCode = 512
        versionName = "5.1.2"
        ndk { abiFilters += listOf("arm64-v8a", "x86_64") }
    }

    // Signierung für die Veröffentlichung: Werte kommen aus GitHub-Secrets (siehe ANLEITUNG).
    val keystorePath = System.getenv("DW2_KEYSTORE")
    signingConfigs {
        if (keystorePath != null) {
            create("release") {
                storeFile = file(keystorePath)
                storePassword = System.getenv("DW2_KEYSTORE_PASSWORD")
                keyAlias = System.getenv("DW2_KEY_ALIAS")
                keyPassword = System.getenv("DW2_KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            if (keystorePath != null) signingConfig = signingConfigs.getByName("release")
        }
    }

    packaging { jniLibs { useLegacyPackaging = true } }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

kotlin { jvmToolchain(17) }

chaquopy {
    defaultConfig {
        version = "3.13"
        pip {
            install("numpy")
            install("pillow")
        }
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("androidx.webkit:webkit:1.12.1")
    implementation("androidx.activity:activity-ktx:1.10.1")
}
