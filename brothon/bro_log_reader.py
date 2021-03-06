"""BroLogReader: This class reads in various Bro IDS logs. The class inherits from
                 the FileTailer class so it supports the following use cases:
                   - Read contents of a Bro log file        (tail=False)
                   - Read contents + 'tail -f' Bro log file (tail=True)
       Args:
            filepath (str): The full path the file (/full/path/to/the/file.txt)
            delimiter (str): The delimiter in the Bro IDS logs (default='\t')
            tail (bool): Do a dynamic tail on the file (i.e. tail -f) (default=False)
"""

import os
import time
import datetime

# Local Imports
from brothon.utils import file_tailer, file_utils


class BroLogReader(file_tailer.FileTailer):
    """BroLogReader: This class reads in various Bro IDS logs. The class inherits from
                     the FileTailer class so it supports the following use cases:
                       - Read contents of a Bro log file        (tail=False)
                       - Read contents + 'tail -f' Bro log file (tail=True)
           Args:
                filepath (str): The full path the file (/full/path/to/the/file.txt)
                delimiter (str): The delimiter in the Bro IDS logs (default='\t')
                tail (bool): Do a dynamic tail on the file (i.e. tail -f) (default=False)
    """

    def __init__(self, filepath, delimiter='\t', tail=False):
        """Initialization for the BroLogReader Class"""
        self._filepath = filepath
        self._delimiter = delimiter
        self._tail = tail

        # Setup the Bro to Python Type mapper
        self.field_names = []
        self.type_converters = []
        self.type_mapper = {'bool': lambda x: True if x == 'T' else False,
                            'count': int,
                            'int': int,
                            'double': float,
                            'time': lambda x: datetime.datetime.fromtimestamp(float(x)),
                            'interval': lambda x: datetime.timedelta(seconds=float(x)),
                            'string': lambda x: x,
                            'port': int,
                            'unknown': lambda x: x}

        # Initialize the Parent Class
        super(BroLogReader, self).__init__(self._filepath, full_read=True, tail=self._tail)

    def readrows(self):
        """The readrows method reads in the header of the Bro log and
            then uses the parent class to yield each row of the log file
            as a dictionary of {key:value, ...} based on Bro header.
        """
        # Calling the internal _readrows so we can catch issues/log rotations
        reconnecting = True
        while True:
            # Yield the rows from the internal reader
            try:
                for row in self._readrows():
                    if reconnecting:
                        print('Successfully monitoring {:s}...'.format(self._filepath))
                        reconnecting = False
                    yield row
            except IOError:
                # If the tail option is set then we do a retry (might just be a log rotation)
                if self._tail:
                    print('Could not open file {:s} Retrying...'.format(self._filepath))
                    reconnecting = True
                    time.sleep(5)
                    continue
                else:
                    break

            # If the tail option is set then we do a retry (might just be a log rotation)
            if self._tail:
                print('File closed {:s} Retrying...'.format(self._filepath))
                reconnecting = True
                time.sleep(5)
                continue
            else:
                break

        # Okay we must be all done
        raise StopIteration

    def _readrows(self):
        """Internal method _readrows, see readrows() for description"""

        # Read in the Bro Headers
        offset, self.field_names, self.type_converters = self._parse_bro_header(self._filepath)

        # Use parent class to yield each row as a dictionary
        for line in self.readlines(offset=offset):

            # Check for #close
            if line.startswith('#close'):
                raise StopIteration

            # Yield the line as a dict
            yield self.make_dict(line.strip().split(self._delimiter))

    def _parse_bro_header(self, bro_log):
        """Parse the Bro log header section.
           TODO: Review parsing logic

            Format example:
                #separator \x09
                #set_separator	,
                #empty_field	(empty)
                #unset_field	-
                #path	httpheader_recon
                #fields	ts	origin	useragent	header_events_json
                #types	time	string	string	string
        """

        # Open the Bro logfile
        with open(bro_log, 'r') as bro_file:

            # Skip until you find the #fields line
            _line = bro_file.readline()
            while not _line.startswith('#fields'):
                _line = bro_file.readline()

            # Read in the field names
            field_names = _line.strip().split(self._delimiter)[1:]

            # Read in the types
            _line = bro_file.readline()
            field_types = _line.strip().split(self._delimiter)[1:]

            # Setup the type converters
            type_converters = []
            for field_type in field_types:
                type_converters.append(self.type_mapper.get(field_type, self.type_mapper['unknown']))

            # Keep the header offset
            offset = bro_file.tell()

        # Return the header info
        return offset, field_names, type_converters

    def make_dict(self, field_values):
        ''' Internal method that makes sure any dictionary elements
            are properly cast into the correct types.
        '''
        data_dict = {}
        for key, value, converter in zip(self.field_names, field_values, self.type_converters):
            try:
                data_dict[key] = '-' if value == '-' else converter(value)
            except ValueError as exc:
                print('Conversion Issue for key:{:s} value:{:s}\n{:s}'.format(key, str(value), str(exc)))
                data_dict[key] = value

        return data_dict


def test():
    """Test for BroLogReader Python Class"""

    # Grab a test file
    data_path = file_utils.relative_dir(__file__, '../data')

    # For each file, create the Class and test the reader
    files = ['app_stats.log', 'conn.log', 'dhcp.log', 'dns.log', 'files.log', 'ftp.log',
             'http.log', 'notice.log', 'smtp.log', 'ssl.log', 'weird.log', 'x509.log']
    for bro_log in files:
        test_path = os.path.join(data_path, bro_log)
        print('Opening Data File: {:s}'.format(test_path))
        reader = BroLogReader(test_path, tail=False)  # First with no tailing
        for line in reader.readrows():
            print(line)
    print('Read with NoTail Test successful!')

    # Test some of the error conditions
    reader.field_names = ['good', 'error']
    reader.type_converters = [int, lambda x: datetime.datetime.fromtimestamp(float(x))]
    reader.make_dict([5, '0, .5, .5'])

    # Now include tailing (note: as an automated test this needs to timeout quickly)
    try:
        from interruptingcow import timeout

        # Spin up the class
        tailer = BroLogReader(test_path, tail=True)

        # Tail the file for 2 seconds and then quit
        try:
            with timeout(2, exception=RuntimeError):
                for line in tailer.readrows():
                    print(line)
        except RuntimeError:  # InterruptingCow raises a RuntimeError on timeout
            print('Tailing Test successful!')

    except ImportError:
        print('Tailing Test not run, need interruptcow module...')


if __name__ == '__main__':
    # Run the test for easy testing/debugging
    test()
