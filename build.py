"""Build a standalone one-file overlay executable (M6).

    python build.py

Produces dist/halo-overlay.exe — a windowed (no-console) build of the Halo overlay renderer
that runs without a Python/dev environment. Users can drop a `settings.json` next to the .exe
to configure hotkeys/colors/etc. (common.py checks there first when frozen).

The exe is only the OVERLAY. The MCP server / CLI still run from Python (they need the agent's
Python env anyway); they auto-launch the overlay, or you can run halo-overlay.exe directly.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    import PyInstaller.__main__

    settings = os.path.join(HERE, "config", "settings.json")
    PyInstaller.__main__.run([
        os.path.join(HERE, "overlay", "__main__.py"),
        "--name", "halo-overlay",
        "--onefile",
        "--windowed",            # no console window (like pythonw)
        "--noconfirm",
        "--clean",
        "--paths", HERE,         # so `import common` resolves
        "--add-data", f"{settings}{os.pathsep}config",
        "--distpath", os.path.join(HERE, "dist"),
        "--workpath", os.path.join(HERE, "build"),
        "--specpath", HERE,
    ])
    exe = os.path.join(HERE, "dist", "halo-overlay.exe")
    if os.path.exists(exe):
        print(f"\nBuilt {exe} ({os.path.getsize(exe) / 1e6:.1f} MB)")
    else:
        print("\nBuild finished but exe not found — check PyInstaller output above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
