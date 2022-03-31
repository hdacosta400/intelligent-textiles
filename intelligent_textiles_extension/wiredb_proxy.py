import sqlite3
import inkex



'''
Proxy for interacting with database storing wire information
'''
class WireDBProxy:
    def __init__(self):
        self.wire_db = "wire_db"
        self.init_wire_group_database()

    def init_wire_group_database(self):
        conn = sqlite3.connect(self.wire_db)
        cursor = conn.cursor()
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS wire_group_table
        (wire_IDs text);''')
        conn.commit()
        conn.close()

    def insert_new_wire_group(self, wire_ids):
        '''
        wire_ids: list of wireids (strings)
        '''
        id_string = ','.join(wire_ids)
        conn = sqlite3.connect(self.wire_db)
        cursor = conn.cursor()
        cursor.execute('''
        INSERT into wire_group_table VALUES (?);''', (id_string,))
        conn.commit()
        conn.close()
    
    def retrieve_all_wire_groups(self):
        conn = sqlite3.connect(self.wire_db)
        cursor = conn.cursor()
        result = cursor.execute('''SELECT * FROM wire_group_table''').fetchall()
        groups = []
        for g_tuple in result: groups.extend([wire_id.split(',') for wire_id in g_tuple])
        conn.commit()
        conn.close()
        return groups
    
    def retrieve_wire_group_with_id(self, wire_id):
        conn = sqlite3.connect(self.wire_db)
        cursor = conn.cursor()
        result = cursor.execute('''
        SELECT * FROM wire_group_table WHERE wire_IDs LIKE ('%' || ? || '%');''', (wire_id,)).fetchall()
        groups = []
        for g_tuple in result: groups.extend([wire_id.split(',') for wire_id in g_tuple])
        inkex.errormsg("what are groups retrieved:{}".format(groups))
        conn.commit()
        conn.close()
        return groups[0] if groups != [] else []
    
    def delete_wire_groups_with_id(self, wire_ids):
        '''
        wire_ids: list of wire_ids to delete
        '''

        #get groupings from wire_ids
        groups = []
        allocated_ids = []
        for w_id in wire_ids:
            if w_id not in allocated_ids:
                group = self.retrieve_wire_group_with_id(w_id)
                allocated_ids.extend(group)
                groups.append(group)
        
        # delete groupings from table
        conn = sqlite3.connect(self.wire_db)
        cursor = conn.cursor()
        for group in groups:
            group_str = ','.join(group)
            result = cursor.execute(''' DELETE FROM wire_group_table WHERE wire_IDs= ? ''', (group_str,)).fetchall()
            groups = []
            for g_tuple in result: groups.extend([wire_id.split(',') for wire_id in g_tuple])
            inkex.errormsg("what are groups retrieved:{}".format(groups))
        conn.commit()
        conn.close()
        return True


