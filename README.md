# qt6_windows7_patches

Patches that make **qtbase 6.11.2** build and run on **Windows 7, 8 and 8.1**, and restore
the ANGLE OpenGL ES / EGL backend Qt 6 dropped.

## Applying

```
git clone https://github.com/desktop-app/qt6_windows7_patches.git qt6_windows7
```

```
win:
    if exist "..\..\patches\qt6_windows7" (
        for %%i in (..\..\patches\qt6_windows7\*.patch) do (
            git apply %%i --ignore-whitespace -v
            if errorlevel 1 (
                echo ERROR: Applying patch %%~nxi failed!
                exit /b 1
            )
        )
    )
    for /r %%i in (..\..\patches\qtbase_%QT%\*) do (
        git apply %%i --ignore-whitespace -v
        ...
    )
```

This series first, `qtbase_$QT` on top.

## The series

Cumulative, apply in order. `0001` is the upstream backport as it came, everything after it
is a separate change on top.

| Patch | Files | What it is |
| --- | --- | --- |
| 0001 | 39 | Windows 7 backport, from [qr243vbi/qt6windows7](https://github.com/qr243vbi/qt6windows7) |
| 0002 | 1 | DirectComposition on Windows 7 path, with `FLIP_SEQUENTIAL` |
| 0003 | 1 | 6.11 `notifyRoleChange` UI Automation call routed through wrapper |
| 0004 | 40 | ANGLE OpenGL ES and EGL backend, from [dimula73/qtbase](https://github.com/dimula73/qtbase) `for-krita/6.11.0`, minus its env-gated resize experiments |
| 0005 | 1 | ANGLE entry points resolved statically, so `libEGL.dll` and `libGLESv2.dll` are not shipped |
| 0006 | 1 | Render-to-texture hole clipped to repainted region, also from Krita fork |

## What it does

Qt 6 assumes Windows 10 APIs are always present; the series resolves them at runtime and
falls back on Windows 7. Stock Qt 6 behaviour is kept on newer Windows.

DirectComposition is Windows 8+, so Windows 7 gets the plain swap chain path. QRhi over D3D11
also needs `ID3D11DeviceContext1` from the Platform Update (KB2670838); without it Qt falls
back to OpenGL, and ANGLE over Direct3D 9Ex covers drivers with no usable desktop OpenGL.

## Moving to a new Qt version

```
tools/port_to_version.sh v6.11.2 v6.12.0
```

Re-merges every patched file against upstream and regenerates the series into `<workdir>/out`,
one commit per patch. Review, then copy over. 6.11.1 to 6.11.2 cost one conflict in 12 touched
files.

## Line endings

LF everywhere, pinned by `.gitattributes`, because qtbase is LF. A CRLF checkout makes every
file conflict during a port.
