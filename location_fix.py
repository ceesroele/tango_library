from readmixxx import create_connection

def replace_dir(s):
    old = '/Volumes/Samsung SSD 860 EVO 500G/'
    new = '/Users/cjr/Tango/'
    new_s = s.replace(old, new)
    return new_s


def fix_location():
    conn = create_connection()
    cursor = conn.cursor()
    sql = "SELECT id, location, directory from track_locations WHERE directory LIKE '/Volumes/Samsung%'"
    cursor.execute(sql)
    rows = cursor.fetchall()
    print('found', len(rows))
    for row in rows:
        id, location, directory = row
        print(f"OLD: {id} # {location} # {directory}")
        print(f"NEW: {id} # {replace_dir(location)} # {replace_dir(directory)}")

        update_sql = "UPDATE track_locations SET location = ?, directory = ? WHERE id = ?"
        try:
            cursor.execute(update_sql, (replace_dir(location), replace_dir(directory), id))
            conn.committ()
        except:
            print(f"Failed to update {id} {location} -- {directory}")

    conn.commit()
    cursor.close()
    conn.close()

if __name__ == '__main__':
    fix_location()