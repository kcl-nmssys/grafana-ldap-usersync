#!/usr/bin/python

import argparse
import ldap
import mysql.connector
import sys
import yaml

parser = argparse.ArgumentParser()
parser.add_argument('--mode')
args = parser.parse_args()
if not args.mode or (args.mode != 'check' and args.mode != 'update'):
    sys.stderr.write('No --mode specified - must be check or update\n')
    sys.exit(1)

mode = args.mode

try:
    with open('config.yaml') as fh:
        config = yaml.load(fh)
except:
    sys.stderr.write('Failed loading config file\n')
    sys.exit(2)

try:
    cnx = mysql.connector.connect(host=config['grafana_db']['hostname'], user=config['grafana_db']['username'], password=config['grafana_db']['password'], database=config['grafana_db']['database'])
except:
    sys.stderr.write('Failed to connect to Grafana database\n')
    sys.exit(3)

try:
    ldap_c = ldap.initialize('ldaps://%s:636' % config['ldap']['hostname'])
    ldap_c.simple_bind_s(config['ldap']['username'], config['ldap']['password'])
except:
    sys.stderr.write('Failed to bind to LDAP\n')
    sys.exit(4)

users = {}

cursor = cnx.cursor()

if mode == 'check':
    result = 1
else:
    query_update = 'UPDATE user SET email = %s, name = %s, is_admin = %s, is_disabled = %s WHERE login = %s'

# Get current users/admins from DB
query = 'SELECT login, email, name, is_admin, is_disabled FROM user WHERE login <> "admin"'
cursor.execute(query)
for (login, email, name, is_admin, is_disabled) in cursor:
    users[login] = {}
    users[login]['grafana'] = {}
    users[login]['grafana']['email'] = email
    users[login]['grafana']['name'] = name
    users[login]['grafana']['is_admin'] = is_admin
    users[login]['grafana']['is_disabled'] = is_disabled
    users[login]['ldap'] = users[login]['grafana'].copy()
    users[login]['verified'] = False

# Check each user in LDAP
for login in users.keys():
    # Normal users
    result_id = ldap_c.search(config['ldap']['userbase'], ldap.SCOPE_SUBTREE, '(&(%s=%s)(%s=%s))' % (config['ldap']['username_attrib'], login, config['ldap']['memberof_attrib'], config['ldap']['users_group']), [config['ldap']['username_attrib'], config['ldap']['email_attrib'], config['ldap']['name_attrib']])
    result_type, result_data = ldap_c.result(result_id, 0)
    if result_data != []:
        users[login]['ldap']['email'] = result_data[0][1][config['ldap']['email_attrib']][0]
        users[login]['ldap']['name'] = result_data[0][1][config['ldap']['name_attrib']][0]
        users[login]['ldap']['is_disabled'] = 0
        users[login]['verified'] = True

    # Admin users
    result_id = ldap_c.search(config['ldap']['userbase'], ldap.SCOPE_SUBTREE, '(&(%s=%s)(%s=%s))' % (config['ldap']['username_attrib'], login, config['ldap']['memberof_attrib'], config['ldap']['admins_group']), [config['ldap']['username_attrib'], config['ldap']['email_attrib'], config['ldap']['name_attrib']])
    result_type, result_data = ldap_c.result(result_id, 0)
    if result_data != []:
        users[login]['ldap']['email'] = result_data[0][1][config['ldap']['email_attrib']][0]
        users[login]['ldap']['name'] = result_data[0][1][config['ldap']['name_attrib']][0]
        users[login]['ldap']['is_disabled'] = 0
        users[login]['ldap']['is_admin'] = 1
        users[login]['verified'] = True

    if not users[login]['verified']:
        users[login]['ldap']['is_disabled'] = 1

    # Update user if LDAP data doesn't match Grafana DB
    if users[login]['ldap'] != users[login]['grafana']:
        print('Updating user %s' % login)
        print('%s > %s' % (users[login]['grafana'], users[login]['ldap']))
        if mode == 'check':
            result = 0
        else:
            cursor.execute(query_update, (users[login]['ldap']['email'], users[login]['ldap']['name'], users[login]['ldap']['is_admin'], users[login]['ldap']['is_disabled'], login))

if mode == 'update':
    cnx.commit()
else:
    sys.exit(result)
