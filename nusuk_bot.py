import runpy
import sys

if __name__ == "__main__":
    try:
        runpy.run_path("nusuk_render.py", run_name="__main__")
    except SystemExit:
        raise
    except Exception as e:
        print(f"[FATAL] nusuk_bot shim error: {e}", file=sys.stderr)
        sys.exit(1)
