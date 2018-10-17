#
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
#


from __future__ import unicode_literals
from __future__ import division
from __future__ import absolute_import
from __future__ import print_function

import unittest2 as unittest
from proton          import Message, Timeout
from system_test     import TestCase, Qdrouterd, main_module, Process
from proton.handlers import MessagingHandler
from proton.reactor  import Container

import time
import math
from qpid_dispatch_internal.compat import UNICODE





#------------------------------------------------
# Helper classes for all tests.
#------------------------------------------------

class Timeout(object):
    """
    Named timeout object can handle multiple simultaneous
    timers, by telling the parent which one fired.
    """
    def __init__ ( self, parent, name ):
        self.parent = parent
        self.name   = name

    def on_timer_task ( self, event ):
        self.parent.timeout ( self.name )



class ManagementMessageHelper ( object ):
    """
    Format management messages.
    """
    def __init__ ( self, reply_addr ):
        self.reply_addr = reply_addr

    def make_router_link_query ( self ) :
        props = { 'count':      '100',
                  'operation':  'QUERY',
                  'entityType': 'org.apache.qpid.dispatch.router.link',
                  'name':       'self',
                  'type':       'org.amqp.management'
                }
        attrs = []
        attrs.append ( UNICODE('linkType') )
        attrs.append ( UNICODE('linkDir') )
        attrs.append ( UNICODE('deliveryCount') )
        attrs.append ( UNICODE('priority') )

        msg_body = { }
        msg_body [ 'attributeNames' ] = attrs
        return Message ( body=msg_body, properties=props, reply_to=self.reply_addr )




#================================================================
#     Setup
#================================================================

class PriorityTests ( TestCase ):

    @classmethod
    def setUpClass(cls):
        super(PriorityTests, cls).setUpClass()

        def router(name, more_config):

            config = [ ('router',  {'mode': 'interior', 'id': name, 'workerThreads': 4}),
                       ('address', {'prefix': 'closest',   'distribution': 'closest'}),
                       ('address', {'prefix': 'balanced',  'distribution': 'balanced'}),
                       ('address', {'prefix': 'multicast', 'distribution': 'multicast'})
                     ]    \
                     + more_config

            config = Qdrouterd.Config(config)

            cls.routers.append(cls.tester.qdrouterd(name, config, wait=True))

        cls.routers = []

        link_cap = 100
        A_client_port = cls.tester.get_port()
        B_client_port = cls.tester.get_port()
        C_client_port = cls.tester.get_port()

        A_inter_router_port = cls.tester.get_port()
        B_inter_router_port = cls.tester.get_port()
        C_inter_router_port = cls.tester.get_port()

        A_config = [
                     ( 'listener',
                       { 'port': A_client_port,
                         'role': 'normal',
                         'stripAnnotations': 'no',
                         'linkCapacity': link_cap
                       }
                     ),
                     ( 'listener',
                       { 'role': 'inter-router',
                         'port': A_inter_router_port,
                         'stripAnnotations': 'no',
                         'linkCapacity': link_cap
                       }
                     ),
                     ( 'address', 
                       { 'prefix': 'speedy',   
                         'distribution': 'closest',
                         'priority': 7
                       }
                     ),
                   ]

        cls.B_config = [
                         ( 'listener',
                           { 'port': B_client_port,
                             'role': 'normal',
                             'stripAnnotations': 'no',
                             'linkCapacity': link_cap
                           }
                         ),
                         ( 'listener',
                           { 'role': 'inter-router',
                             'port': B_inter_router_port,
                             'stripAnnotations': 'no',
                             'linkCapacity': link_cap
                           }
                         ),
                         ( 'connector',
                           { 'name': 'BA_connector',
                             'role': 'inter-router',
                             'port': A_inter_router_port,
                             'verifyHostname': 'no',
                             'stripAnnotations': 'no',
                             'linkCapacity': link_cap
                           }
                         )
                      ]

        C_config = [
                     ( 'listener',
                       { 'port': C_client_port,
                         'role': 'normal',
                         'stripAnnotations': 'no',
                         'linkCapacity': link_cap
                       }
                     ),
                     ( 'listener',
                       { 'role': 'inter-router',
                         'port': C_inter_router_port,
                         'stripAnnotations': 'no',
                         'linkCapacity': link_cap
                       }
                     ),
                     ( 'connector',
                       { 'name': 'CB_connector',
                         'role': 'inter-router',
                         'port': B_inter_router_port,
                         'verifyHostname': 'no',
                         'stripAnnotations': 'no',
                         'linkCapacity': link_cap
                       }
                     )
                  ]


        router ( 'A', A_config )
        router ( 'B', cls.B_config )
        router ( 'C', C_config )


        router_A = cls.routers[0]
        router_B = cls.routers[1]
        router_C = cls.routers[2]

        router_A.wait_router_connected('B')
        router_A.wait_router_connected('C')

        cls.client_addrs = ( router_A.addresses[0],
                             router_B.addresses[0],
                             router_C.addresses[0]
                           )


    def all_routers_are_running ( self ) :
        print ( "are all routers running?" )
        for router in self.routers :
          if None != router.poll() :
            print ( "no!" )
            return False
          print ( "  ok" )
        return True


    def test_priority ( self ):
        name = 'test_01'
        test = Priority ( self,
                          name,
                          self.client_addrs,
                          "speedy/01"
                        )
        test.run()
        self.assertEqual ( None, test.error )



#================================================================
#     Tests
#================================================================


class Priority ( MessagingHandler ):

    def __init__ ( self, parent, test_name, client_addrs, destination ):
        super(Priority, self).__init__(prefetch=10)

        self.parent          = parent
        self.client_addrs    = client_addrs
        self.dest            = destination

        self.error           = None
        self.sender          = None
        self.receiver        = None
        self.test_timer      = None
        self.send_timer      = None
        self.n_messages      = 100
        self.n_sent          = 0
        self.n_accepted      = 0
        self.n_released      = 0
        self.send_conn       = None
        self.recv_conn       = None
        self.n_messages      = 100
        self.n_received      = 0
        self.reactor         = None
        self.timer_count     = 0
        self.routers = {
                         'A' : dict(),
                         'B' : dict(),
                         'C' : dict()
                       }
        self.sent_queries   = False
        self.received_answers = 0
        self.finishing = False



    # Shut down everything and exit.
    def bail ( self, text ):
        self.finishing = True
        print ( "bailing..." )
        self.test_timer.cancel ( )
        self.send_timer.cancel ( )

        self.error = text
        print ( "error == ", self.error )

        self.routers['A'] ['mgmt_conn'].close()
        self.routers['B'] ['mgmt_conn'].close()
        self.routers['C'] ['mgmt_conn'].close()

        self.send_conn.close()
        self.recv_conn.close ( )
        print ( "done bailing..." )




    def on_start ( self, event ):
        self.reactor = event.reactor
        self.test_timer = event.reactor.schedule ( 30, Timeout(self, "test") )
        self.send_conn  = event.container.connect ( self.client_addrs[0] )  # A
        self.recv_conn  = event.container.connect ( self.client_addrs[2] )  # C

        self.sender     = event.container.create_sender ( self.send_conn, self.dest )
        self.receiver   = event.container.create_receiver ( self.recv_conn, self.dest )
        self.receiver.flow ( 100 )

        self.routers['A'] ['mgmt_conn']     = event.container.connect ( self.client_addrs[0] )
        self.routers['A'] ['mgmt_receiver'] = event.container.create_receiver ( self.routers['A'] ['mgmt_conn'], dynamic=True )
        self.routers['A'] ['mgmt_sender']   = event.container.create_sender   ( self.routers['A'] ['mgmt_conn'], "$management" )

        self.routers['B'] ['mgmt_conn']     = event.container.connect ( self.client_addrs[1] )
        self.routers['B'] ['mgmt_receiver'] = event.container.create_receiver ( self.routers['B'] ['mgmt_conn'], dynamic=True )
        self.routers['B'] ['mgmt_sender']   = event.container.create_sender   ( self.routers['B'] ['mgmt_conn'], "$management" )

        self.routers['C'] ['mgmt_conn']     = event.container.connect ( self.client_addrs[2] )
        self.routers['C'] ['mgmt_receiver'] = event.container.create_receiver ( self.routers['C'] ['mgmt_conn'], dynamic=True )
        self.routers['C'] ['mgmt_sender']   = event.container.create_sender   ( self.routers['C'] ['mgmt_conn'], "$management" )

        self.send_timer = event.reactor.schedule ( 2, Timeout(self, "send") )



    def timeout ( self, name ):
        if self.finishing :
            return
        self.timer_count += 1
        print ( "timer count %d ========================================================" % self.timer_count )

        if name == 'send':
            self.send ( )
            if not self.sent_queries :
                print ( "schedule" )
                self.test_timer = self.reactor.schedule ( 1, Timeout(self, "send") )

        elif name == 'test':
            self.bail ( "test is hanging" )
            return



    def on_link_opened ( self, event ) :
        # The A mgmt link has opened. Create its management helper.

        # ( Now we know the address that the management helper should use as its "reply-to". )
        if event.receiver == self.routers['A'] ['mgmt_receiver'] :
            print ("Link opened to mgmt A!" )
            event.receiver.flow ( 1000 )
            self.routers['A'] ['mgmt_helper'] = ManagementMessageHelper ( event.receiver.remote_source.address )

        elif event.receiver == self.routers['B'] ['mgmt_receiver'] :
            print ("Link opened to mgmt B!" )
            event.receiver.flow ( 1000 )
            self.routers['B'] ['mgmt_helper'] = ManagementMessageHelper ( event.receiver.remote_source.address )

        elif event.receiver == self.routers['C'] ['mgmt_receiver'] :
            print ("Link opened to mgmt C!" )
            event.receiver.flow ( 1000 )
            self.routers['C'] ['mgmt_helper'] = ManagementMessageHelper ( event.receiver.remote_source.address )



    def send ( self ) :
        if self.sender.credit <= 0:
            self.receiver.flow ( 100 )
            print ( "send: flow." )
            return

        if self.n_sent < self.n_messages :
            for i in xrange(50) :
                msg = Message ( body=self.n_sent )
                msg.priority = 3
                self.sender.send ( msg )
                self.n_sent += 1
            print ( "send: n_sent == %d" % self.n_sent )
        elif not self.sent_queries  :
            mgmt_helper = self.routers['A'] ['mgmt_helper']
            mgmt_sender = self.routers['A'] ['mgmt_sender']
            msg = mgmt_helper.make_router_link_query ( )
            mgmt_sender.send ( msg )

            mgmt_helper = self.routers['B'] ['mgmt_helper']
            mgmt_sender = self.routers['B'] ['mgmt_sender']
            msg = mgmt_helper.make_router_link_query ( )
            mgmt_sender.send ( msg )

            self.sent_queries = True

            


    def on_message ( self, event ) :

        msg = event.message

        if event.receiver == self.routers['A'] ['mgmt_receiver'] :
            print ( "Got mgmt msg from A!!!" , msg )
            if 'results' in msg.body :
                results = msg.body['results']
                for i in range(len(results)) :
                    result = results[i]
                    if "inter-router" == result[0] and "out" == result[1] :
                        message_count = result[2]
                        priority      = result[3]
                        print ( "ROUTER A: At priority", priority, "we have", message_count, "messages" )
                self.received_answers += 1
                if self.received_answers >= 2 :
                    self.bail ( None )

        elif event.receiver == self.routers['B'] ['mgmt_receiver'] :
            print ( "Got mgmt msg from B!!!" , msg )
            if 'results' in msg.body :
                results = msg.body['results']
                for i in range(len(results)) :
                    result = results[i]
                    if "inter-router" == result[0] and "out" == result[1] :
                        message_count = result[2]
                        priority      = result[3]
                        print ( "ROUTER B: At priority", priority, "we have", message_count, "messages" )
                self.received_answers += 1
                if self.received_answers >= 2 :
                    self.bail ( None )
                        
        else :
            self.n_received += 1
            if not (self.n_received % 10) :
                print ( "received: %d" % self.n_received )
            if self.n_received >= self.n_messages :
                print ( "receive -- all messages are in -- do something else!" )



    def run(self):
        Container(self).run()



if __name__ == '__main__':
    unittest.main(main_module())
