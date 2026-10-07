import unittest

from backend.coordinator.subtasks import SnapshotSubtask, completed_subtasks, unresolved_subtasks


class SubtaskStatusTests(unittest.TestCase):
    def test_closed_cancelled_and_done_subtasks_are_not_routed_again(self):
        statuses = ["Done", "Closed", "Won't Do", "Won’t Do", "Cancelled", "Resolved", "Released", "Ready for test",
                    "TO DO QA", "CODE REVIEW QA", "In Progress"]
        subtasks = [SnapshotSubtask(str(index), "Sub-task", status, status) for index, status in enumerate(statuses)]
        self.assertEqual(statuses[:8], [item.status for item in completed_subtasks(subtasks)])
        self.assertEqual(statuses[8:], [item.status for item in unresolved_subtasks(subtasks)])
