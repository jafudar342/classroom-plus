"""Desktop entry point; never writes user records into the installed application."""
import argparse
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description='Classroom+ local attendance studio')
    parser.add_argument('--workspace', type=Path, help='A private workspace folder (default: per-user application data)')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--initialize-only', action='store_true', help='Create an empty workspace without starting the server')
    parser.add_argument('--check-runtime', action='store_true', help='Check bundled dependencies without downloading weights')
    args = parser.parse_args()
    from workspace import initialize, user_workspace
    try:
        root = initialize(args.workspace or user_workspace())
        os.environ['DEEPFACE_HOME'] = str(root / 'models')
        os.environ['DEEPFACE_BACKEND_ENGINE'] = 'onnx'
        os.environ['MPLCONFIGDIR'] = str(root / 'work/matplotlib')
        if args.initialize_only:
            print('Empty workspace ready:', root); return 0
        if args.check_runtime:
            from deepface import DeepFace
            import cv2, onnxruntime, tornado
            from server import WEB, make_app
            assert (WEB / 'index.html').is_file(), 'Web assets are missing'
            make_app(root).engine.registry()
            print('Runtime ready:', DeepFace.__version__, cv2.__version__, onnxruntime.__version__, tornado.version)
            return 0
        from server import run
        return run(root, args.port, open_browser=not args.no_browser)
    except (RuntimeError, OSError, ValueError) as error:
        print('Classroom+:', error, file=sys.stderr); return 1


if __name__ == '__main__':
    raise SystemExit(main())
