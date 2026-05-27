import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("migration.log", encoding="utf-8"),
    ],
)

from migrator import Migrator  # noqa: E402


def main():
    try:
        Migrator().run()
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("Interrupted — progress saved, re-run to resume.")
        sys.exit(0)


if __name__ == "__main__":
    main()
