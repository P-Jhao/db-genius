from app.adapters.relational import RelationalAdapter


class MySqlAdapter(RelationalAdapter):
    db_type = "mysql"
    dialect = "mysql"
    driver = "mysql+pymysql"
    default_port = 3306
    mysql_protocol = True
