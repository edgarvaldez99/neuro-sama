# Logger de colores para la consola. Mantiene el estilo str.format() y una
# variable FILE_URI en mayúsculas (del código original), así que silenciamos
# esos avisos de estilo de pylint.
# pylint: disable=invalid-name,consider-using-f-string
import logging
import os
import time

# Formatos ANSI de color ({} es el placeholder del texto a imprimir).
_RED = "\033[91m {}\033[00m"
_GREEN = "\033[92m {}\033[00m"
_YELLOW = "\033[93m {}\033[00m"
_BLUE = "\033[94m {}\033[00m"
_CYAN = "\033[96m {}\033[00m"


class Logger:

    def __init__(
        self,
        console_log=False,
        file_logging=False,
        file_uri=None,
        level=logging.DEBUG,
        override=False,
        log_name="baselog",
    ):
        self.log_name = log_name
        self.console_log = console_log
        self.file_logging = file_logging
        if not file_logging:
            return
        FILE_URI = self._resolve_file_uri(file_uri, override)
        self.file_uri = FILE_URI
        logging.basicConfig(
            filename=FILE_URI,
            encoding="utf-8",
            level=level,
            format="%(asctime)s %(message)s",
        )

    def _resolve_file_uri(self, file_uri, override):
        """Determina la ruta del log a archivo y prepara el directorio."""
        if file_uri is None:
            default_name = "{}_log_{}.txt".format(
                self.log_name, time.asctime(time.localtime())
            )
            return default_name.replace(" ", "_").replace(":", "-")
        if os.path.exists(file_uri) and not override:
            raise NameError("Log File already exists! Try setting override flag")
        if os.path.exists(file_uri) and override:
            os.remove(file_uri)
        if not os.path.exists(file_uri):
            os.makedirs("logs", exist_ok=True)
        return file_uri.replace(" ", "_").replace(":", "-")

    def warning(self, skk, printout=True):  # yellow
        if printout and self.console_log:
            print(
                _YELLOW.format("WARNING:"),
                _YELLOW.format(skk),
            )
        if self.file_logging:
            logging.warning(skk)

    def error(self, skk, printout=True):  # red
        if printout and self.console_log:
            print(
                _RED.format("ERROR:"),
                _RED.format(skk),
            )
        if self.file_logging:
            logging.error(skk)

    def fail(self, skk, printout=True):  # red
        if printout and self.console_log:
            print(
                _RED.format("FATAL:"),
                _RED.format(skk),
            )
        if self.file_logging:
            logging.exception(skk)

    def passing(self, skk, printout=True):  # green
        if printout and self.console_log:
            print(_GREEN.format(skk))
        if self.file_logging:
            logging.info(skk)

    def passingblue(self, skk, printout=True):  # blue
        if printout and self.console_log:
            print(_CYAN.format(skk))
        if self.file_logging:
            logging.info(skk)

    def info(self, skk, printout=True):  # blue
        if printout and self.console_log:
            print(
                _BLUE.format("Info:"),
                _BLUE.format(skk),
            )
        if self.file_logging:
            logging.debug(skk)
