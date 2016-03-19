import unittest
import datetime
import os
import inspect

from peewee import CharField, DateField, BooleanField, SqliteDatabase
from playhouse.versioned import VersionedModel

sqlite_database = SqliteDatabase(':memory:')


# Basic example class
class People(VersionedModel):
    class Meta:
        database = sqlite_database


class Person(People):
    name = CharField()
    birthday = DateField()
    is_relative = BooleanField()


class TestVersionedModel(unittest.TestCase):

    def setUp(self):
        Person.create_table()
        self.person_kwargs = {'name': 'test_person',
                              'birthday': datetime.date.today(),
                              'is_relative': True
                              }
        self.person = Person.create(**self.person_kwargs)

    def tearDown(self):
        Person.drop_table()

    def test_should_create_and_select_as_normal_model(self):
        loaded_person = Person.get(id=self.person.id)
        self.assertEqual(loaded_person, self.person)
        for key, value in self.person_kwargs.items():
            self.assertEqual(value, getattr(loaded_person, key))
            self.assertEqual(getattr(self.person, key), getattr(loaded_person, key))

    def test_should_update_as_normal_model(self):
        self.person.is_relative = False  # toggle
        self.person.save()
        loaded_person = Person.get(id=self.person.id)
        self.assertEqual(loaded_person.is_relative, False)

    def test_should_delete_as_normal_model(self):
        old_id = self.person.id
        self.person.delete_instance()
        self.assertRaises(Person.DoesNotExist, Person.get, id=old_id)

    def test_should_not_create_database_file(self):
        '''
        Make sure the nested class is inheriting the ':memory:' database setting.
        If not, the default ``peewee.db`` file will be created
        '''
        self.assertFalse(os.path.exists('peewee.db'))

    def test_should_create_nested_version_models(self):
        self.assertTrue(hasattr(Person, '_VersionModel'), 'Should have a _version_model attribute')
        self.assertTrue(issubclass(Person._VersionModel, Person))

    def test_should_not_infinitely_recurse_when_creating_nested_version_models(self):
        self.assertFalse(inspect.isclass(Person._VersionModel._VersionModel))
        self.assertTrue(Person._VersionModel._VersionModel is None)

    def test_version_model_should_have_same_attributes(self):
        current_version = self.person._get_current_version()
        for key, value in self.person_kwargs.items():
            self.assertEqual(getattr(current_version, key), value)

    def test_newly_created_model_should_have_deleted_false(self):
        current_version = self.person._get_current_version()
        self.assertFalse(current_version.deleted)

    def test_newly_created_version_model_should_have_valid_until_null(self):
        current_version = self.person._get_current_version()
        self.assertIsNone(current_version.valid_until)

    def test_deleteing_instance_should_create_new_version(self):
        original_versions = Person._VersionModel.select()
        self.assertEqual(len(original_versions), 1, 'should begin with one version')
        self.assertFalse(original_versions[0].deleted)

        # delete the instance
        self.person.delete_instance()

        # reload the versions
        versions = Person._VersionModel.select()
        self.assertEqual(len(versions), 2, 'should now have 2 versions')

        # First one should have valid_until == ``NULL`` and deleted == ``True``.
        # The second one should not
        null_count = 0
        deleted_count = 0
        for version in versions:
            if version.valid_until is None:
                null_count += 1
            if version.deleted is True:
                deleted_count += 1
        self.assertEqual(null_count, 1)
        self.assertEqual(deleted_count, 1)

        # Check all attributes
        for key, value in self.person_kwargs.items():
            for version in versions:
                self.assertEqual(getattr(version, key), value)

    def test_update_should_create_new_version(self):
        original_versions = Person._VersionModel.select()
        self.assertEqual(len(original_versions), 1, 'should begin with one version')
        self.assertFalse(original_versions[0].deleted)

        # modify the instance
        self.person.name = 'new name'
        self.person.save()

        # reload the versions
        versions = Person._VersionModel.select()
        self.assertEqual(len(versions), 2, 'should now have 2 versions')

        # current one should have valid_until == ``NULL``
        # the second should have a real date
        null_count = 0
        for version in versions:
            if version.valid_until is None:
                null_count += 1
        self.assertEqual(null_count, 1)

        # Check attributes of old version
        old_version = (self.person._versions
                       .where(Person._VersionModel.valid_until.is_null(False))
                       )[0]
        for key, value in self.person_kwargs.items():
                self.assertEqual(getattr(old_version, key), value)

        # Check attributes of current version
        current_version = self.person._get_current_version()
        for key in self.person_kwargs.keys():
                self.assertEqual(getattr(current_version, key), getattr(self.person, key))

    def test_create_new_record_with_save_should_create_version(self):
        new_person = Person()
        for key, value in self.person_kwargs.items():
            setattr(new_person, key, value)
        new_person.save()

        self.assertIsNotNone(new_person._get_current_version())

    def test_version_model_should_have_version_id(self):
        current_version = self.person._get_current_version()
        self.assertEqual(current_version.version_id, 1)

    def test_parent_model_should_have_version_id(self):
        self.assertEqual(self.person.version_id, 1)

    def test_version_id_shold_increment(self):
        test_versions_names = ((num, str(num)) for num in range(2, 100))  # (2, '2'), (3, '3')...
        for version, name in test_versions_names:
            self.person.name = name
            self.person.save()
            # check
            current_version = self.person._get_current_version()
            self.assertEqual(current_version.version_id, version)
            self.assertEqual(self.person.version_id, version)

    def test_revert(self):
        version_1 = self.person_kwargs
        version_2 = version_1.copy()
        version_2['name'] = 'new_name'

        # first make a change
        for field, value in version_2.items():
            setattr(self.person, field, value)
        self.person.save()

        # verify it stuck
        for field, value in version_2.items():
            self.assertEqual(getattr(self.person, field), value)

        # save this new version 2 for latter
        version_2_instance = self.person._get_current_version()

        # revert to version 1 using an integer
        self.person.revert(1)
        # verify
        for field, value in version_1.items():
            self.assertEqual(getattr(self.person, field), value)

        # try to go back to version 2 again using an instance
        self.person.revert(version_2_instance)
        # verify
        for field, value in version_2.items():
            self.assertEqual(getattr(self.person, field), value)

        # check we are actually at version 4
        # 1 -> 2 -> 1 -> 2 == 4
        self.assertEqual(self.person.version_id, 4)



if __name__ == '__main__':
    unittest.main()
