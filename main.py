from pathlib import Path
import traceback


def _write_startup_error() -> None:
    log_path = Path(__file__).resolve().with_name("startup_error.log")
    try:
        with log_path.open("a", encoding="utf-8") as log:
            log.write("\n--- startup failure ---\n")
            traceback.print_exc(file=log)
    except Exception:
        pass


if __name__ == "__main__":
    try:
        from app import run_app
        run_app()
    except BaseException:
        _write_startup_error()
        raise
