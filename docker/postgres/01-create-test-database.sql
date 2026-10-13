-- Creates the dedicated database used by the backend's PostgreSQL tests, so they
-- never touch the development database. The postgres image runs this only when it
-- initialises an empty data volume; see README.md for an existing volume.
CREATE DATABASE leadflow_test;
