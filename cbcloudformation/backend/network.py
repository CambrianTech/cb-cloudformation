from collections import namedtuple
import troposphere as ts
import troposphere.ec2


BackendNetwork = namedtuple("BackendNetwork", [
    "vpc",
    "pub_sub", "pub_sub2",
    "internet_gateway", "internet_gateway_attachment",
    "pub_route_table", "pub_internet_route",
    "pub_subnet_route_table_association", "pub_subnet2_route_table_association",
    "network_acl",
])


def create_network(template: ts.Template) -> BackendNetwork:
    tags_stack_id = ts.Tags(Application=ts.Ref("AWS::StackId"))

    # Create VPC
    vpc = template.add_resource(
        ts.ec2.VPC("VPC", CidrBlock="10.0.0.0/16", Tags=tags_stack_id)
    )

    # Create subnets
    pub_sub = template.add_resource(
        ts.ec2.Subnet("PublicSubnet", CidrBlock="10.0.0.0/24",
                        VpcId=vpc.ref(), Tags=tags_stack_id,
                        AvailabilityZone=ts.Sub("${AWS::Region}a"))
    )

    pub_sub2 = template.add_resource(
        ts.ec2.Subnet("PublicSubnet2", CidrBlock="10.0.1.0/24",
                        VpcId=vpc.ref(), Tags=tags_stack_id,
                        AvailabilityZone=ts.Sub("${AWS::Region}f"))
    )

    # Create and attach internet gateway to public subnet
    internet_gateway = template.add_resource(
        ts.ec2.InternetGateway("InternetGateway", Tags=tags_stack_id)
    )

    internet_gateway_attachment = template.add_resource(
        ts.ec2.VPCGatewayAttachment(
            "AttachInternetGatewayToPublicSubdomain",
            VpcId=vpc.ref(),
            InternetGatewayId=internet_gateway.ref()
        )
    )

    # Create route table and routes to internet
    pub_route_table = template.add_resource(
        ts.ec2.RouteTable(
            "RouteTable",
            VpcId=vpc.ref(),
            Tags=tags_stack_id
        )
    )

    pub_internet_route = template.add_resource(
        ts.ec2.Route(
            "PublicInternetRoute",
            DependsOn=internet_gateway_attachment.title,
            GatewayId=internet_gateway.ref(),
            DestinationCidrBlock="0.0.0.0/0",
            RouteTableId=pub_route_table.ref()
        )
    )

    pub_subnet_route_table_association = template.add_resource(
        ts.ec2.SubnetRouteTableAssociation(
            "PublicSubnetRouteTableAssociation",
            SubnetId=pub_sub.ref(),
            RouteTableId=pub_route_table.ref()
        )
    )

    pub_subnet2_route_table_association = template.add_resource(
        ts.ec2.SubnetRouteTableAssociation(
            "PublicSubnet2RouteTableAssociation",
            SubnetId=pub_sub2.ref(),
            RouteTableId=pub_route_table.ref()
        )
    )

    # Create access control list
    network_acl = template.add_resource(
        ts.ec2.NetworkAcl(
            "NetworkAcl",
            VpcId=vpc.ref(),
            Tags=tags_stack_id
        )
    )

    # TODO: ACL Rules

    return BackendNetwork(
        vpc,
        pub_sub, pub_sub2,
        internet_gateway, internet_gateway_attachment,
        pub_route_table, pub_internet_route,
        pub_subnet_route_table_association, pub_subnet2_route_table_association,
        network_acl,
    )
