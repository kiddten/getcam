### postgres init
* install postgres
* `sudo -iu postgres`
* `initdb -D /var/lib/postgres/data` don't required on ubuntu (apt-get install includes that)
* create db `createdb myDatabaseName`
* start primary database shell `psql -d myDatabaseName`
* add your user to postgres users `createuser --interactive` (optional)
* create user and grant access to db
```bash
sudo -u postgres psql
```
```sql
CREATE DATABASE test_database;
CREATE USER test_user WITH password 'qwerty';
GRANT ALL ON DATABASE test_database TO test_user;
```
```bash
psql -h localhost test_database test_user
```
* db_uri format 
`postgresql://user:password@localhost/dbname`
