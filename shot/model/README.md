### postgres init
* install postgres
* `sudo -iu postgres`
* `initdb -D /var/lib/postgres/data`
* add your user to postgres users `createuser --interactive`
* create db `createdb myDatabaseName`
* start primary database shell `psql -d myDatabaseName`