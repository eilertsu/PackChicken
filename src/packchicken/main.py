from packchicken.config import get_settings
from packchicken.utils.logging import setup_logging, get_logger

def main():
    s = get_settings()
    setup_logging(level=s.LOG_LEVEL, json_output=(s.LOG_FORMAT == "json"))
    log = get_logger("packchicken.bootstrap")
    log.info("PackChicken starting…")
    for line in s.summary_lines():
        log.info(line)

if __name__ == "__main__":
    main()
