import requests
import json
import yaml
import urllib3
import sys
import time
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class NDRESTClientClass:

    def __init__(self, base_uri, username, pwd, login_domain = "local", verify = False):
        self.base_uri = base_uri
        self.username = username
        self.pwd = pwd
        self.login_domain = login_domain
        self.verify = verify
        self.session = requests.session()
        self.headers = {
            "Content-Type": "application/json"
            }
        self.token = None

    def nd_rest_req(self, api_endpoint_uri, method, payload_data=None, headers = {}, req_timeout = 600.0, login_required = True):
        if login_required == True and self.token == None:
            raise Exception("Login is required but not performed prior to this request, Please call nd_login() first}")
        req_uri = self.base_uri + api_endpoint_uri
        req_headers = self.headers
        if self.token != None:
            req_headers["Authorization"] = f"Bearer {self.token}"
        if headers != {}:
            req_headers.update(headers)
        req = requests.Request(method=method.upper(), url=req_uri, headers=req_headers, json=payload_data)
        prepared_req = req.prepare()
        rest_resp = self.session.send(prepared_req, verify=self.verify, timeout = req_timeout)
        return rest_resp

    def nd_login(self):
        login_creds = {
            "domain": self.login_domain,
            "userName": self.username,
            "userPasswd": self.pwd
        }
        login_resp = self.nd_rest_req(api_endpoint_uri='/login', method='POST', payload_data=login_creds, req_timeout= 2.0, login_required=False)
        if login_resp.status_code == 200:
            print(f"Successfully logged in to {self.base_uri}")
            self.token = str(login_resp.json()["jwttoken"])
        else:
            print(f"Login to {self.base_uri} failed with status code: {login_resp.status_code}. Error: {login_resp.text}")
        return login_resp

class VRFConfigurationClass:

    def __init__(self, fabric, vrfName, vrfTemplate, vrfExtensionTemplate, vrfTemplateConfig):
        self.fabric = fabric
        self.vrfName = vrfName
        self.vrfTemplate = vrfTemplate
        self.vrfExtensionTemplate = vrfExtensionTemplate
        self.vrfTemplateConfig = vrfTemplateConfig

    def to_dict(self):
        return {
            "fabric": self.fabric,
            "vrfName": self.vrfName,
            "vrfTemplate": self.vrfTemplate,
            "vrfExtensionTemplate": self.vrfExtensionTemplate,
            "vrfTemplateConfig": self.vrfTemplateConfig
        }

    @classmethod
    def from_dict(cls,data):
        vrf_obj = cls(**data)
        return vrf_obj
    
    @staticmethod
    def build_vrfs(data_from_file):
        vrf_list = data_from_file.get("vrfs", [])
        if not vrf_list:
            print ("No VRFs found in yml file. Exiting...")
            sys.exit()
        return [VRFConfigurationClass.from_dict(single_vrf) for single_vrf in vrf_list]
    
    @staticmethod
    def create_vrf_on_ndfc(vrf_list, nd_rest_client, fabric_name):
        for vrf in vrf_list:
            vrf_dict = vrf.to_dict()
            rest_resp = nd_rest_client.nd_rest_req(api_endpoint_uri=f"/appcenter/cisco/ndfc/api/v1/lan-fabric/rest/top-down/v2/fabrics/{fabric_name}/vrfs", payload_data=vrf_dict, method="POST")
            if rest_resp.status_code == 200:
                print("#####################################################")
                print(f"Created VRFs:\n{rest_resp.text}")
                print("#####################################################")
            else:
                print(f"Create VRF {vrf_dict['vrfName']} failed with status code: {rest_resp.status_code}. Error:\n{rest_resp.text}")
        return

class VRFAttachmentClass:

    def __init__(self, vrfName, lanAttachList):
        self.vrfName = vrfName
        self.lanAttachList = lanAttachList

    def to_dict(self):
        return {
            "vrfName": self.vrfName,
            "lanAttachList": self.lanAttachList
        }
    
    @classmethod
    def from_dict(cls,data):
        vrf_attach_obj = cls(**data)
        return vrf_attach_obj
    
    @staticmethod
    def build_vrf_attachments(data_from_file):
        vrf_attachments = data_from_file.get("vrf_attachments", [])
        if not vrf_attachments:
            print ("No VRF attachments found in yml file. Exiting...")
            sys.exit()
        return [VRFAttachmentClass.from_dict(vrf_attachment) for vrf_attachment in vrf_attachments]
    
    @staticmethod
    def adjust_vrf_attachments(vrf_attachments, nd_rest_client, fabric_name):
        #Get serial to switch mapping in dictionary form
        serial_to_switch = get_serial_to_switch_dict_by_fabric(nd_rest_client, fabric_name)
        #replace switchname with serial number
        for vrf in vrf_attachments:
            for attach in vrf.lanAttachList:
                attach["serialNumber"] = convert_switch_to_serial(attach["serialNumber"],serial_to_switch)
    
    @staticmethod
    def create_vrf_attachment_ndfc(vrf_attachments, nd_rest_client, fabric_name):
        attach_list = []
        #convert vrf attachments from class object to dictionary
        for vrf_attachment in vrf_attachments:
            attach_list.append(vrf_attachment.to_dict())
        #Send REST POST request to create the attachments on NDFC fabric switches
        rest_resp = nd_rest_client.nd_rest_req(api_endpoint_uri=f"/appcenter/cisco/ndfc/api/v1/lan-fabric/rest/top-down/v2/fabrics/{fabric_name}/vrfs/attachments", payload_data=attach_list, method="POST")
        if rest_resp.status_code == 200:
            print("#####################################################")
            print(f"Created VRF Attachments:\n{rest_resp.text}")
            print("#####################################################")
        else:
            print(f"Create VRF Attachments failed with status code: {rest_resp.status_code}. Error:\n{rest_resp.text}")
        return

    @staticmethod
    def deploy_vrf_attachments_ndfc(vrf_attachments, nd_rest_client):
        deploy_vrf_dict = {}
        for vrf in vrf_attachments:
            for attach in vrf.lanAttachList:
                key = attach["serialNumber"]
                if key in deploy_vrf_dict:
                    deploy_vrf_dict[key].add(vrf.vrfName)
                else:
                    deploy_vrf_dict[key]=set()
                    deploy_vrf_dict[key].add(vrf.vrfName)
        #Convert the set to a string
        for serial in deploy_vrf_dict:
            deploy_vrf_dict[serial] = ','.join(deploy_vrf_dict[serial])
        #deploy the vrf on ndfc switches
        rest_resp = nd_rest_client.nd_rest_req(api_endpoint_uri=f"/appcenter/cisco/ndfc/api/v1/lan-fabric/rest/top-down/v2/vrfs/deploy", payload_data=deploy_vrf_dict, method="POST")
        if rest_resp.status_code == 200:
            print("#####################################################")
            print(f"Deployed VRF Attachment:\n{deploy_vrf_dict}\n{rest_resp.text}")
            print("#####################################################")
        else:
            print(f"Deploy VRF Attachments failed with status code: {rest_resp.status_code}. Error:\n{rest_resp.text}")
        return


class NetworkConfigurationClass:

    def __init__(self,fabric, vrf, networkName, networkTemplateConfig, networkTemplate):
        self.fabric = fabric
        self.vrf = vrf
        self.networkName = networkName
        self.networkTemplateConfig = networkTemplateConfig
        self.networkTemplate = networkTemplate

    def to_dict(self):
        return {
            "fabric": self.fabric,
            "vrf": self.vrf,
            "networkName": self.networkName,
            "networkTemplateConfig": self.networkTemplateConfig,
            "networkTemplate": self.networkTemplate
        }
    @classmethod
    def from_dict(cls,data):
        nw_obj = cls(**data)
        return nw_obj
    
    @staticmethod
    def build_nws(data_from_file):
        nw_list = data_from_file.get("networks",[])
        if not nw_list:
            print ("No Networks found in yml file. Exiting...")
            sys.exit()
        return [NetworkConfigurationClass.from_dict(single_nw) for single_nw in nw_list]
    
    @staticmethod
    def create_nw_on_ndfc(nw_list, nd_rest_client, fabric_name):
        for nw in nw_list:
            nw_dict = nw.to_dict()
            #old /appcenter/cisco/ndfc/api/v1/lan-fabric/rest/top-down/fabrics/{fabric_name}/networks
            rest_resp = nd_rest_client.nd_rest_req(api_endpoint_uri=f"/appcenter/cisco/ndfc/api/v1/lan-fabric/rest/top-down/v2/fabrics/{fabric_name}/networks", payload_data=nw_dict, method="POST")
            if rest_resp.status_code == 200:
                print("#####################################################")
                print(f"Created Network:\n{rest_resp.text}")
                print("#####################################################")
            else:
                print(f"Create Network {nw_dict['networkName']} failed with status code: {rest_resp.status_code}. Error:\n{rest_resp.text}")
        return

class NetworkAttachmentClass:
    def __init__(self, networkName, lanAttachList):
        self.networkName = networkName
        self.lanAttachList = lanAttachList
    
    def to_dict(self):
        return {
            "networkName": self.networkName,
            "lanAttachList": self.lanAttachList
        }
    
    @classmethod
    def from_dict(cls,data):
        nw_attach_obj = cls(**data)
        return nw_attach_obj

    @staticmethod
    def build_nw_attachments(data_from_file):
        nw_attachments = data_from_file.get("nw_attachments", [])
        if not nw_attachments:
            print ("No Networks attachments found in yml file. Exiting...")
            sys.exit()
        return [NetworkAttachmentClass.from_dict(nw_attachment) for nw_attachment in nw_attachments]
    
    @staticmethod
    def adjust_nw_attachments(nw_attachments, nd_rest_client, fabric_name):
        #Get serial to switch mapping in dictionary form
        serial_to_switch = get_serial_to_switch_dict_by_fabric(nd_rest_client, fabric_name)
        #replace switchname with serial number
        for nw in nw_attachments:
            for attach in nw.lanAttachList:
                attach["serialNumber"] = convert_switch_to_serial(attach["serialNumber"],serial_to_switch)

    @staticmethod
    def create_nw_attachment_ndfc(nw_attachments, nd_rest_client, fabric_name):
        attach_list = []
        #convert vrf attachments from class object to dictionary
        for nw_attachment in nw_attachments:
            attach_list.append(nw_attachment.to_dict())
        #Send REST POST request to create the attachments on NDFC fabric switches
        rest_resp = nd_rest_client.nd_rest_req(api_endpoint_uri=f"/appcenter/cisco/ndfc/api/v1/lan-fabric/rest/top-down/v2/fabrics/{fabric_name}/networks/attachments", payload_data=attach_list, method="POST")
        if rest_resp.status_code == 200:
            print("#####################################################")
            print(f"Created Network Attachment:\n{rest_resp.text}")
            print("#####################################################")
        else:
            print(f"Create Network Attachment failed with status code: {rest_resp.status_code}. Error:\n{rest_resp.text}")
        return

    @staticmethod
    def deploy_nw_attachments_ndfc(nw_attachments, nd_rest_client):
        deploy_nw_dict = {}
        for nw in nw_attachments:
            for attach in nw.lanAttachList:
                key = attach["serialNumber"]
                if key in deploy_nw_dict:
                    deploy_nw_dict[key].add(nw.networkName)
                else:
                    deploy_nw_dict[key]=set()
                    deploy_nw_dict[key].add(nw.networkName)
        #Convert the set to a string
        for serial in deploy_nw_dict:
            deploy_nw_dict[serial] = ','.join(deploy_nw_dict[serial])
        print("Deploy network")
        print(deploy_nw_dict)
        #deploy the network on ndfc switches
        rest_resp = nd_rest_client.nd_rest_req(api_endpoint_uri=f"/appcenter/cisco/ndfc/api/v1/lan-fabric/rest/top-down/v2/networks/deploy", payload_data=deploy_nw_dict, method="POST")
        if rest_resp.status_code == 200:
            print("#####################################################")
            print(f"Deployed Network Attachment:\n{deploy_nw_dict}\n{rest_resp.text}")
            print("#####################################################")
        else:
            print(f"Deploy Network Attachments failed with status code: {rest_resp.status_code}. Error:\n{rest_resp.text}")
        return

def get_serial_to_switch_dict_by_fabric(nd_rest_client, fabric_name):
    rest_resp = nd_rest_client.nd_rest_req(api_endpoint_uri=f"/appcenter/cisco/ndfc/api/v1/lan-fabric/rest/control/fabrics/{fabric_name}/inventory/switchesByFabric", payload_data={}, method="GET")
    switches = rest_resp.json()
    serial_to_switch = {}
    for switch in switches:
        serial_to_switch[switch["serialNumber"]] = switch["logicalName"]
    return serial_to_switch

def convert_switch_to_serial(switch_name,serial_to_switch):
    for serial, switch in serial_to_switch.items():
        if switch == switch_name:
            return serial
    return ""

def check_user_input(message: str):
    while True:
        #uncomment below two lines to proceed with all steps without user confirmations:
        #option = 'y'
        #break
        option = input(f"{message} (Enter yes/skip/exit or y/s/e):")
        if option.lower() in ('y','s','e','yes','skip','exit'):
            break
        print("Invalid input, try again:")
    if option.lower() in ('y','yes'):
        print("Proceeding...")
        return 1
    if option.lower() in ('s','skip'):
        print("Skipping...")
        return 0
    if option.lower() in ('e','exit'):
        print("Exiting as requested by user")
        sys.exit()

def read_from_yml(file_path):
    with open(file_path, "r") as yml_file:
        file_data = yaml.safe_load(yml_file)
    return file_data

def check_status_and_wait(nd_rest_client, check_status_of):
    keys_to_parse = {}
    resource_names = []
    resources_on_ndfc = []
    retry_time = 20
    max_retries = 6
    retries = 0
    api_endpoints = { 
        "vrf_uri": f"/appcenter/cisco/ndfc/api/v1/lan-fabric/rest/top-down/fabrics/{check_status_of['fabric_name']}/vrfs",
        "network_uri": f"/appcenter/cisco/ndfc/api/v1/lan-fabric/rest/top-down/fabrics/{check_status_of['fabric_name']}/networks",
    }
    if 'fabric_name' not in check_status_of or 'resource'  not in check_status_of or 'resource_type'  not in check_status_of or 'desired_state' not in check_status_of:
        print ("Cannot check status, one of the parameters is missing, skipping status check.")
        return
    if not nd_rest_client:
        print ("Existing ND REST Client is required to check status, skipping status check.")
        return
    if check_status_of['resource_type'] == 'vrf':
        keys_to_parse = {'name':'vrfName','status':'vrfStatus'}
        for vrf in check_status_of['resource']:
            resource_names.append(vrf.vrfName)
        api_endpoint = api_endpoints["vrf_uri"]
    if check_status_of['resource_type'] == 'network':
        keys_to_parse = {'name':'networkName','status':'networkStatus'}
        for nw in check_status_of['resource']:
            resource_names.append(nw.networkName)
        api_endpoint = api_endpoints["network_uri"]
    
    while True:
        status_not_okay = 0
        resource_status = {}
        rest_resp = nd_rest_client.nd_rest_req(api_endpoint_uri=api_endpoint, payload_data={}, method="GET")
        if rest_resp.status_code != 200:
            print ('Querying NDFC failed, skipping status check...')
            return
        resources_on_ndfc = rest_resp.json()
        for name in resource_names:
            resource_found = 0
            for resource in resources_on_ndfc:
                if name != resource[keys_to_parse['name']]:
                    continue
                resource_found = 1
                resource_status[name] = resource[keys_to_parse['status']]
                if resource[keys_to_parse['status']] not in check_status_of['desired_state']:
                    status_not_okay = 1
            if resource_found != 1:
                print (f"Resource {name} not found on NDFC")
                status_not_okay = 1
        if status_not_okay == 0:
            print (f"{resource_status} are in desired state: {check_status_of['desired_state']}.")
            return
        retries = retries + 1
        print (f"Resources not in desired state {check_status_of['desired_state']} or resource(s) not found: {resource_status}")
        print (f"Retry count: {retries}, waiting for {retry_time}s for next check")
        if retries % 3 == 0:
            #To fix OUT-OF-SYNC or PENDING state upon recreating existing resoruce, trigger fabric wide deployment:
            print("Triggering fabric wide deployment")
            r = nd_rest_client.nd_rest_req(api_endpoint_uri=f"/appcenter/cisco/ndfc/api/v1/lan-fabric/rest/control/fabrics/{check_status_of['fabric_name']}/config-deploy/", payload_data={}, method="POST")
            if r.status_code != 200:
                print(f"Failed to trigger fabric wide deployment with status code: {r.status_code}. Error:\n{r.text}")
                continue
            print("Triggered fabric wide deployment successfully.")
        if retries >= max_retries:
            print (f"Maximum retries:{max_retries} reached, continuing to next step...")
            return
        print(f"Waiting for {retry_time}s...")
        time.sleep(retry_time)

def main():
    fabric_name = "DevNet_Fabric"
    check_status_of = dict()
    check_status_of['fabric_name'] = fabric_name
    yml_file_path = "config_data_python.yml"
    # Read yml file
    data_from_file = read_from_yml(yml_file_path)
    devnet_nd = NDRESTClientClass(base_uri="https://10.10.20.60", username="admin", pwd="REPLACE_WITH_PASSWORD")
    # Login to ND
    login=devnet_nd.nd_login()
    if login.status_code != 200:
        print (f"Login to NDFC failed with status code: {login.status_code}. Error:\n{login.text}")
        sys.exit()
    
    message = "Proceed with task Create VRFs?"
    select = check_user_input(message)
    if select == 1:
        #Load list of VRFs from yml file data
        list_of_vrfs = VRFConfigurationClass.build_vrfs(data_from_file)
        #Create the VRFs on NDFC fabric one by one
        VRFConfigurationClass.create_vrf_on_ndfc(list_of_vrfs, devnet_nd, fabric_name)
        #Check status:
        check_status_of['resource'] = list_of_vrfs
        check_status_of['resource_type'] = 'vrf'
        check_status_of['desired_state'] = ('NA','DEPLOYED')
        check_status_and_wait(devnet_nd, check_status_of)
    
    message = "Proceed with task Create VRFs Attachments?"
    select = check_user_input(message)
    if select == 1:
        #Load list of VRF attachments from yml file data
        vrf_attachments = VRFAttachmentClass.build_vrf_attachments(data_from_file)
        #Adjust the attachments by replacing switch names with their serial numbers
        VRFAttachmentClass.adjust_vrf_attachments(vrf_attachments, devnet_nd, fabric_name)
        #Create VRF attachments on NDFC fabric
        VRFAttachmentClass.create_vrf_attachment_ndfc(vrf_attachments, devnet_nd, fabric_name)
        #Check status:
        check_status_of['resource'] = vrf_attachments
        check_status_of['resource_type'] = 'vrf'
        check_status_of['desired_state'] = ('PENDING','DEPLOYED')
        check_status_and_wait(devnet_nd, check_status_of)

        message = "Proceed with task Deploy VRFs Attachments?"
        select = check_user_input(message)
        if select == 1:
            #Deploy VRF attachments on NDFC switches
            VRFAttachmentClass.deploy_vrf_attachments_ndfc(vrf_attachments, devnet_nd)
            time.sleep(15)
            #Check status:
            check_status_of['resource'] = vrf_attachments
            check_status_of['resource_type'] = 'vrf'
            check_status_of['desired_state'] = ('DEPLOYED')
            check_status_and_wait(devnet_nd, check_status_of)

    message = "Proceed with task Create Networks?"
    select = check_user_input(message)
    if select == 1:
        #Load list of NWs from yml file data
        list_of_nws = NetworkConfigurationClass.build_nws(data_from_file)
        #Create the NWs on NDFC fabric one by one
        NetworkConfigurationClass.create_nw_on_ndfc(list_of_nws, devnet_nd, fabric_name)
        #Check status:
        check_status_of['resource'] = list_of_nws
        check_status_of['resource_type'] = 'network'
        check_status_of['desired_state'] = ('NA','DEPLOYED')
        check_status_and_wait(devnet_nd, check_status_of)
        
    message = "Proceed with task Create Network Attachments?"
    select = check_user_input(message)
    if select == 1:
        #Load list of NW attachments from yml file data
        nw_attachments = NetworkAttachmentClass.build_nw_attachments(data_from_file)
        #Adjust the NW attachments by replacing switch names with their serial numbers
        NetworkAttachmentClass.adjust_nw_attachments(nw_attachments, devnet_nd, fabric_name)
        #Create Network attachments on NDFC switches
        NetworkAttachmentClass.create_nw_attachment_ndfc(nw_attachments, devnet_nd, fabric_name)
        #Check status:
        check_status_of['resource'] = nw_attachments
        check_status_of['resource_type'] = 'network'
        check_status_of['desired_state'] = ('PENDING','DEPLOYED')
        check_status_and_wait(devnet_nd, check_status_of)
        
        message = "Proceed with task Deploy Networks Attachments?"
        select = check_user_input(message)
        if select == 1:
            #Deploy Network attahments on NDFC switches
            NetworkAttachmentClass.deploy_nw_attachments_ndfc(nw_attachments, devnet_nd)
            time.sleep(15)
            #Check status:
            check_status_of['resource'] = nw_attachments
            check_status_of['resource_type'] = 'network'
            check_status_of['desired_state'] = ('DEPLOYED')
            check_status_and_wait(devnet_nd, check_status_of)

if __name__ == '__main__':
    main()