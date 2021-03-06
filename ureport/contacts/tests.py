# -*- coding: utf-8 -*-

from __future__ import unicode_literals
from datetime import datetime
from django.utils import timezone

from dash.orgs.models import TaskState

from mock import patch
import pytz
from ureport.contacts.models import ContactField, Contact, ReportersCounter
from ureport.contacts.tasks import pull_contacts
from ureport.locations.models import Boundary
from ureport.tests import UreportTest, TembaContactField, MockTembaClient, TembaContact
from temba_client.v1.types import Group as TembaGroup
from ureport.utils import json_date_to_datetime


class ContactFieldTest(UreportTest):
    def setUp(self):
        super(ContactFieldTest, self).setUp()

    def test_kwargs_from_temba(self):
        temba_contact_field = TembaContactField.create(key='foo', label='Bar', value_type='T')

        kwargs = ContactField.kwargs_from_temba(self.nigeria, temba_contact_field)
        self.assertEqual(kwargs, dict(org=self.nigeria, key='foo', label='Bar', value_type='T'))

        # try creating contact from them
        ContactField.objects.create(**kwargs)

    def test_update_or_create_from_temba(self):
        temba_contact_field = TembaContactField.create(key='foo', label='Bar', value_type='T')

        field = ContactField.update_or_create_from_temba(self.nigeria, temba_contact_field)

        self.assertEqual(field.key, 'foo')
        self.assertEqual(field.label, 'Bar')

        updated_field = ContactField.update_or_create_from_temba(self.nigeria, temba_contact_field)

        self.assertEqual(field.pk, updated_field.pk)


class ContactTest(UreportTest):
    def setUp(self):
        super(ContactTest, self).setUp()
        self.nigeria.set_config('reporter_group', "Ureporters")
        self.nigeria.set_config('registration_label', "Registration Date")
        self.nigeria.set_config('state_label', "State")
        self.nigeria.set_config('district_label', "LGA")
        self.nigeria.set_config('ward_label', "Ward")
        self.nigeria.set_config('occupation_label', "Activité")
        self.nigeria.set_config('born_label', "Born")
        self.nigeria.set_config('gender_label', 'Gender')
        self.nigeria.set_config('female_label', "Female")
        self.nigeria.set_config('male_label', 'Male')

        # boundaries fetched
        self.country = Boundary.objects.create(org=self.nigeria, osm_id="R-NIGERIA", name="Nigeria",
                                               level=Boundary.COUNTRY_LEVEL, parent=None,
                                               geometry='{"foo":"bar-country"}')
        self.state = Boundary.objects.create(org=self.nigeria, osm_id="R-LAGOS", name="Lagos",
                                             level=Boundary.STATE_LEVEL,
                                             parent=self.country, geometry='{"foo":"bar-state"}')
        self.district = Boundary.objects.create(org=self.nigeria, osm_id="R-OYO", name="Oyo",
                                                level=Boundary.DISTRICT_LEVEL,
                                                parent=self.state, geometry='{"foo":"bar-state"}')
        self.ward = Boundary.objects.create(org=self.nigeria, osm_id="R-IKEJA", name="Ikeja",
                                                level=Boundary.WARD_LEVEL,
                                                parent=self.district, geometry='{"foo":"bar-ward"}')

        self.registration_date = ContactField.objects.create(org=self.nigeria, key='registration_date',
                                                             label='Registration Date', value_type='T')

        self.state_field = ContactField.objects.create(org=self.nigeria, key='state', label='State', value_type='S')
        self.district_field = ContactField.objects.create(org=self.nigeria, key='lga', label='LGA', value_type='D')
        self.ward_field = ContactField.objects.create(org=self.nigeria, key='ward', label='Ward', value_type='W')
        self.occupation_field = ContactField.objects.create(org=self.nigeria, key='occupation', label='Activité',
                                                            value_type='T')

        self.born_field = ContactField.objects.create(org=self.nigeria, key='born', label='Born', value_type='T')
        self.gender_field = ContactField.objects.create(org=self.nigeria, key='gender', label='Gender', value_type='T')

    def test_get_or_create(self):

        self.assertIsNone(Contact.objects.filter(org=self.nigeria, uuid='contact-uuid').first())

        created_contact = Contact.get_or_create(self.nigeria, 'contact-uuid')

        self.assertTrue(created_contact)
        self.assertIsNone(created_contact.born)

        created_contact.born = '2000'
        created_contact.save()

        existing_contact = Contact.get_or_create(self.nigeria, 'contact-uuid')
        self.assertEqual(created_contact.pk, existing_contact.pk)
        self.assertEqual(existing_contact.born, 2000)

    def test_kwargs_from_temba(self):

        temba_contact = TembaContact.create(uuid='C-006', name="Jan", urns=['tel:123'],
                                            groups=['G-001', 'G-007'],
                                            fields={'registration_date': None, 'state': None,
                                                    'lga': None, 'occupation': None, 'born': None,
                                                    'gender': None},
                                            language='eng')

        kwargs = Contact.kwargs_from_temba(self.nigeria, temba_contact)

        self.assertEqual(kwargs, dict(uuid='C-006', org=self.nigeria, gender='', born=0, occupation='',
                                      registered_on=None, state='', district='', ward=''))

        # try creating contact from them
        Contact.objects.create(**kwargs)

        # Invalid boundaries become ''
        temba_contact = TembaContact.create(uuid='C-007', name="Jan", urns=['tel:123'],
                                            groups=['G-001', 'G-007'],
                                            fields={'registration_date': '2014-01-02T03:04:05.000000Z',
                                                    'state': 'Kigali', 'lga': 'Oyo', 'occupation': 'Student',
                                                    'born': '1990', 'gender': 'Male'},
                                            language='eng')

        kwargs = Contact.kwargs_from_temba(self.nigeria, temba_contact)

        self.assertEqual(kwargs, dict(uuid='C-007', org=self.nigeria, gender='M', born=1990, occupation='Student',
                                      registered_on=json_date_to_datetime('2014-01-02T03:04:05.000'), state='',
                                      district='', ward=''))

        # try creating contact from them
        Contact.objects.create(**kwargs)

        temba_contact = TembaContact.create(uuid='C-008', name="Jan", urns=['tel:123'],
                                            groups=['G-001', 'G-007'],
                                            fields={'registration_date': '2014-01-02T03:04:05.000000Z', 'state':'Lagos',
                                                    'lga': 'Oyo', 'ward': 'Ikeja', 'occupation': 'Student', 'born': '1990',
                                                    'gender': 'Male'},
                                            language='eng')

        kwargs = Contact.kwargs_from_temba(self.nigeria, temba_contact)

        self.assertEqual(kwargs, dict(uuid='C-008', org=self.nigeria, gender='M', born=1990, occupation='Student',
                                      registered_on=json_date_to_datetime('2014-01-02T03:04:05.000'), state='R-LAGOS',
                                      district='R-OYO', ward='R-IKEJA'))

        # try creating contact from them
        Contact.objects.create(**kwargs)

    def test_update_or_create_from_temba(self):
        temba_contact = TembaContact.create(uuid='C-006', name="Jan", urns=['tel:123'],
                                            groups=['G-001', 'G-007'],
                                            fields={'registration_date': None, 'state': None,
                                                    'lga': None, 'occupation': None, 'born': None,
                                                    'gender': None},
                                            language='eng')

        contact = Contact.update_or_create_from_temba(self.nigeria, temba_contact)

        self.assertEqual(contact.uuid, 'C-006')

        updated_contact = Contact.update_or_create_from_temba(self.nigeria, temba_contact)

        self.assertEqual(contact.pk, updated_contact.pk)

    def test_contact_ward_field(self):

        temba_contact = TembaContact.create(uuid='C-0011', name="Jan", urns=['tel:123'],
                                            groups=['G-001', 'G-007'],
                                            fields={'registration_date': '2014-01-02T03:04:05.000000Z', 'state':'Lagos',
                                                    'lga': '', 'ward': 'Ikeja', 'occupation': 'Student', 'born': '1990',
                                                    'gender': 'Male'},
                                            language='eng')

        kwargs = Contact.kwargs_from_temba(self.nigeria, temba_contact)
        # invalid parent boundary (district) will yield empty ward
        self.assertEqual(kwargs, dict(uuid='C-0011', org=self.nigeria, gender='M', born=1990, occupation='Student',
                                      registered_on=json_date_to_datetime('2014-01-02T03:04:05.000'), state='R-LAGOS',
                                      district='', ward=''))

        self.assertEqual(ReportersCounter.get_counts(self.nigeria), dict())
        Contact.objects.create(uuid='C-007', org=self.nigeria, gender='M', born=1990, occupation='Student',
                               registered_on=json_date_to_datetime('2014-01-02T03:04:05.000'), state='R-LAGOS',
                               district='R-OYO', ward='R-IKEJA')
        field_count = ReportersCounter.get_counts(self.nigeria)

        self.assertEqual(field_count['ward:R-IKEJA'], 1)

        Contact.objects.create(uuid='C-008', org=self.nigeria, gender='M', born=1980, occupation='Teacher',
                               registered_on=json_date_to_datetime('2014-01-02T03:07:05.000'), state='R-LAGOS',
                               district='R-OYO', ward='R-IKEJA')

        field_count = ReportersCounter.get_counts(self.nigeria)
        self.assertEqual(field_count['ward:R-IKEJA'], 2)
        Contact.objects.all().delete()

    def test_reporters_counter(self):
        self.assertEqual(ReportersCounter.get_counts(self.nigeria), dict())
        Contact.objects.create(uuid='C-007', org=self.nigeria, gender='M', born=1990, occupation='Student',
                               registered_on=json_date_to_datetime('2014-01-02T03:04:05.000'), state='R-LAGOS',
                               district='R-OYO')

        expected = dict()
        expected['total-reporters'] = 1
        expected['gender:m'] = 1
        expected['occupation:student'] = 1
        expected['born:1990'] = 1
        expected['registered_on:2014-01-02'] = 1
        expected['state:R-LAGOS'] = 1
        expected['district:R-OYO'] = 1

        self.assertEqual(ReportersCounter.get_counts(self.nigeria), expected)

        Contact.objects.create(uuid='C-008', org=self.nigeria, gender='M', born=1980, occupation='Teacher',
                               registered_on=json_date_to_datetime('2014-01-02T03:07:05.000'), state='R-LAGOS',
                               district='R-OYO')

        expected = dict()
        expected['total-reporters'] = 2
        expected['gender:m'] = 2
        expected['occupation:student'] = 1
        expected['occupation:teacher'] = 1
        expected['born:1990'] = 1
        expected['born:1980'] = 1
        expected['registered_on:2014-01-02'] = 2
        expected['state:R-LAGOS'] = 2
        expected['district:R-OYO'] = 2

        self.assertEqual(ReportersCounter.get_counts(self.nigeria), expected)

        self.assertEqual(ReportersCounter.get_counts(self.nigeria, ['total-reporters', 'gender:m']),
                         {'total-reporters': 2, 'gender:m': 2})

    @patch('redis.client.StrictRedis.get')
    def test_squash_reporters(self, mock_redis_get):
        mock_redis_get.return_value = None

        self.assertFalse(ReportersCounter.objects.all())

        counter1 = ReportersCounter.objects.create(org=self.nigeria, type='type-a', count=2)
        counter2 = ReportersCounter.objects.create(org=self.nigeria, type='type-b', count=1)
        counter3 = ReportersCounter.objects.create(org=self.nigeria, type='type-a', count=3)

        self.assertEqual(ReportersCounter.objects.all().count(), 3)
        self.assertEqual(ReportersCounter.objects.filter(type='type-a').count(), 2)

        ReportersCounter.squash_counts()

        self.assertEqual(ReportersCounter.objects.all().count(), 2)
        # type-a counters are squashed into one row
        self.assertFalse(ReportersCounter.objects.filter(pk__in=[counter1.pk, counter3.pk]))
        self.assertEqual(ReportersCounter.objects.filter(type='type-a').count(), 1)

        self.assertTrue(ReportersCounter.objects.filter(pk=counter2.pk))

        counter_type_a = ReportersCounter.objects.filter(type='type-a').first()

        self.assertTrue(counter_type_a.count, 5)


class ContactsTasksTest(UreportTest):
    def setUp(self):
        super(ContactsTasksTest, self).setUp()

    @patch('ureport.contacts.models.ReportersCounter.squash_counts')
    @patch('ureport.tests.TestBackend.pull_fields')
    @patch('ureport.tests.TestBackend.pull_boundaries')
    @patch('ureport.tests.TestBackend.pull_contacts')
    def test_pull_contacts(self, mock_pull_contacts, mock_pull_boundaries, mock_pull_fields, mock_squash_counts):
        mock_pull_fields.return_value = (1, 2, 3, 4)
        mock_pull_boundaries.return_value = (5, 6, 7, 8)
        mock_pull_contacts.return_value = (9, 10, 11, 12)
        mock_squash_counts.return_value = "Called"

        pull_contacts(self.nigeria.pk)

        task_state = TaskState.objects.get(org=self.nigeria, task_key='contact-pull')
        self.assertEqual(task_state.get_last_results(), {
            'fields': {'created': 1, 'updated': 2, 'deleted': 3},
            'boundaries': {'created': 5, 'updated': 6, 'deleted': 7},
            'contacts': {'created': 9, 'updated': 10, 'deleted': 11}
        })

        mock_squash_counts.assert_called_once_with()
