import unittest
from unittest.mock import Mock
from livekit_demo import ReceiverRegistry


class ReceiverTests(unittest.TestCase):
    def test_duplicate_subscription_with_changed_track_id(self):
        registry = ReceiverRegistry()
        task = Mock()
        task.done.return_value = False
        create = Mock(return_value=task)
        self.assertIs(registry.start('caller', '', create), task)
        self.assertIsNone(registry.start('caller', 'TR-new-id', create))
        create.assert_called_once()

    def test_new_call_after_receiver_finishes(self):
        registry = ReceiverRegistry()
        first, second = Mock(), Mock()
        first.done.return_value = False
        registry.start('caller', 'TR1', lambda: first)
        registry.release('caller', first)
        self.assertIs(registry.start('caller', 'TR2', lambda: second), second)

    def test_stale_cleanup_does_not_remove_new_task(self):
        registry = ReceiverRegistry()
        old, new = Mock(), Mock()
        old.done.return_value = True
        registry.start('caller', 'TR1', lambda: old)
        registry.start('caller', 'TR2', lambda: new)
        registry.release('caller', old)
        self.assertIs(registry.active['caller'][1], new)
        registry.unsubscribe('caller', 'TR1')
        new.cancel.assert_not_called()
        registry.unsubscribe('caller', 'TR2')
        new.cancel.assert_called_once()

    def test_separate_callers_still_receive(self):
        registry = ReceiverRegistry()
        first, second = Mock(), Mock()
        self.assertIs(registry.start('one', 'TR1', lambda: first), first)
        self.assertIs(registry.start('two', 'TR2', lambda: second), second)


if __name__ == '__main__':
    unittest.main()
