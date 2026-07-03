import os
import tempfile
import threading
import unittest

from services.iphan._error_registry import (
    ERROR_LOG_NAME,
    ErrorRegistry,
    begin_error_registry,
    error_registry_summary,
    get_error_registry,
    write_error_registry,
)


class TestErrorRegistry(unittest.TestCase):
    def test_write_creates_file_with_details(self):
        registry = ErrorRegistry(contract_key="saip")
        registry.record(
            kind="download",
            message="404 Client Error: Not Found",
            url="https://example.com/file.pdf",
            dest_path=".\\relatorios\\iphan\\saip\\JANEIRO_01-07-14_30\\file.pdf",
            context="HU105 | SAIP20-Sprint11",
        )

        with tempfile.TemporaryDirectory() as tmp:
            path = registry.write(tmp)
            self.assertIsNotNone(path)
            self.assertTrue(os.path.isfile(path))
            with open(path, encoding="utf-8") as handle:
                content = handle.read()
            self.assertIn("Contrato: saip", content)
            self.assertIn("Total: 1", content)
            self.assertIn("404 Client Error", content)
            self.assertIn("HU105 | SAIP20-Sprint11", content)
            self.assertEqual(os.path.basename(path), ERROR_LOG_NAME)

    def test_write_returns_none_when_empty(self):
        registry = ErrorRegistry(contract_key="saip")
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(registry.write(tmp))
            self.assertFalse(os.path.isfile(os.path.join(tmp, ERROR_LOG_NAME)))

    def test_begin_write_and_summary(self):
        begin_error_registry("editais_iphan")
        registry = get_error_registry()
        self.assertIsNotNone(registry)
        registry.record(kind="wiki_resolve", message="falha", url="https://wiki")

        with tempfile.TemporaryDirectory() as tmp:
            path = write_error_registry(tmp)
            self.assertIsNotNone(path)
            self.assertIn("1 erro(s)", error_registry_summary())

        begin_error_registry("saip")
        self.assertEqual(error_registry_summary(), "Registro de erros: nenhum")

    def test_thread_safe_record(self):
        registry = ErrorRegistry(contract_key="saip")

        def worker(index: int) -> None:
            registry.record(kind="download", message=f"erro {index}")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(registry.count(), 20)


if __name__ == "__main__":
    unittest.main()
