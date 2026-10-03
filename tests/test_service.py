"""Core use cases with fake ports: no server, SQLite or parser dependencies."""
import io
from pathlib import Path
import unittest
from unittest.mock import Mock
from backend.domain.models import Course, ParsedDocument, StudyError
from backend.domain.ports import LibraryRepository, FileStore, DocumentParser, AnswerProvider
from backend.service.library import LibraryService

class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.repo = Mock(spec=LibraryRepository)
        self.files = Mock(spec=FileStore)
        self.parser = Mock(spec=DocumentParser)
        self.answers = Mock(spec=AnswerProvider)
        self.service = LibraryService(self.repo, self.files, self.parser, self.answers, 20 * 1024 * 1024)
        self.doc = {"id": "doc", "course_id": "course", "name": "test.pdf", "pages": 5}
        self.repo.document.return_value = self.doc
        self.files.stage.return_value = (Path("staged"), 12, "hash")
        self.files.path.return_value = Path("final")
        self.parser.parse.return_value = ParsedDocument(["text"])

    def test_course_name(self):
        self.assertEqual(Course.create("  数学  ").name, "数学")
        for name in (" ", "a" * 101):
            with self.assertRaises(StudyError):
                self.service.create_course(name)
        self.repo.create_course.assert_not_called()

    def test_parser_failure_keeps_course_and_discards_staged_file(self):
        self.parser.parse.side_effect = ValueError("文件损坏")
        with self.assertRaisesRegex(StudyError, "文件损坏"):
            self.service.import_document("course", "test.pdf", "slides", io.BytesIO(b"test"))
        self.files.discard.assert_called_once_with(Path("staged"))
        self.repo.add_document.assert_not_called()
        self.repo.cancel_pending.assert_not_called()

    def test_database_failure_compensates_final_file(self):
        self.repo.add_document.side_effect = RuntimeError("disk failure")
        with self.assertLogs(level="ERROR"), self.assertRaises(StudyError):
            self.service.import_document("course", "test.pdf", "slides", io.BytesIO(b"test"))
        self.assertIn(unittest.mock.call(Path("final")), self.files.discard.call_args_list)

    def test_course_isolation_and_range_validation(self):
        for course, start, end in (("other", 1, 1), ("course", 4, 2), ("course", 1, 6)):
            with self.assertRaises(StudyError):
                self.service.answer(course, "doc", start, "ask", question="why?", page_end=end)
        self.answers.answer.assert_not_called()
        self.repo.add_messages.assert_not_called()

    def test_cross_page_source_is_frozen_and_persisted_in_pair(self):
        self.repo.page_text.return_value = "page context"
        self.answers.answer.return_value = "演示模式，未连接 AI"
        result = self.service.answer("course", "doc", 2, "ask", selected_text="selected",
                                     question="why?", page_end=4, persist=True)
        pair = self.repo.add_messages.call_args.args[0]
        self.assertEqual([m.role for m in pair], ["user", "assistant"])
        self.assertEqual((pair[1].page_start, pair[1].page_end), (2, 4))
        self.assertEqual(result["citation"]["name"], "test.pdf")
        self.assertEqual(result["message_id"], pair[1].id)

    def test_delete_database_failure_restores_original(self):
        self.files.quarantine.return_value = Path("quarantine")
        self.repo.delete_document.side_effect = RuntimeError("db unavailable")
        with self.assertRaises(RuntimeError):
            self.service.delete_document("doc")
        self.files.restore.assert_called_once_with(Path("quarantine"), self.doc)

    def test_empty_question_and_note_rejected(self):
        with self.assertRaises(StudyError):
            self.service.answer("course", "doc", 1, "ask", question=" ")
        with self.assertRaises(StudyError):
            self.service.save_note("course", "doc", 1, body=" ")

if __name__ == "__main__":
    unittest.main()
