import troposphere as ts
import troposphere.ec2
import troposphere.awslambda
import troposphere.iam


class BackendTemplateFactory:
    def create_template(self) -> ts.Template:
        self.template = ts.Template("Cambrian image processing backend")

        self.ref_stack_id = ts.Ref("AWS::StackId")
        self.tags_stack_id = ts.Tags(Application=self.ref_stack_id)

        self._create_vpc()
        self._create_presigned_url_lambda()

        return self.template

    def _res(self, resource):
        return self.template.add_resource(resource)

    def _create_vpc(self):
        # Create VPC
        self.vpc = self._res(
            ts.ec2.VPC("VPC", CidrBlock="10.0.0.0/16", Tags=self.tags_stack_id)
        )

        # Create subnets
        self.pub_sub = self._res(
            ts.ec2.Subnet("PublicSubnet", CidrBlock="10.0.0.0/24",
                          VpcId=self.vpc.ref(), Tags=self.tags_stack_id)
        )

        self.priv_sub = self._res(
            ts.ec2.Subnet("PrivateSubnet", CidrBlock="10.0.1.0/24",
                          VpcId=self.vpc.ref(), Tags=self.tags_stack_id)
        )

        # Create and attach internet gateway to public subnet
        self.internet_gateway = self._res(
            ts.ec2.InternetGateway("InternetGateway", Tags=self.tags_stack_id)
        )

        self.internet_gateway_attachment = self._res(
            ts.ec2.VPCGatewayAttachment(
                "AttachInternetGatewayToPublicSubdomain",
                VpcId=self.vpc.ref()
            )
        )

        # Create route table and routes to internet
        self.pub_route_table = self._res(
            ts.ec2.RouteTable(
                "RouteTable",
                VpcId=self.vpc.ref(),
                Tags=self.tags_stack_id
            )
        )

        self.pub_internet_route = self._res(
            ts.ec2.Route(
                "PublicInternetRoute",
                DependsOn=self.internet_gateway_attachment.ref(),
                GatewayId=self.internet_gateway.ref(),
                DestinationCidrBlock="0.0.0.0/0",
                RouteTableId=self.pub_route_table.ref()
            )
        )

        self.pub_subnet_route_table_association = self._res(
            ts.ec2.SubnetRouteTableAssociation(
                "PublicSubnetRouteTableAssociation",
                SubnetId=self.pub_sub.ref(),
                RouteTableId=self.pub_route_table.ref()
            )
        )

        self.network_acl = self._res(
            ts.ec2.NetworkAcl(
                "NetworkAcl",
                VpcId=self.vpc.ref(),
                Tags=self.tags_stack_id
            )
        )

        # TODO: ACL Rules

    def _create_presigned_url_lambda(self):
        with open("getimageuploadpresignedurl.js", "r") as code_file:
            code_lines = code_file.readlines()

        self.presigned_url_lambda = self._res(
            ts.awslambda.Function(
                "GetImageUploadPresignedUrl",
                Code=ts.awslambda.Code(ZipFile=ts.Join("", code_lines)),
                Handler="index.handler",
                Role=ts.GetAtt("LambdaExecutionRole", "Arn"),
                Runtime="nodejs",
                MemorySize=128, # TODO: Make this param
                Timeout=3 # TODO: Make this param
            )
        )

        self.presigned_url_lambda_execution_role = self._res(
            ts.iam.Role(
                "GetImageUploadPresignedUrlExecutionRole",
                Path="/",
                Policies=[ts.iam.Policy(
                    PolicyName="root",
                    PolicyDocument={
                        "Version": "2012-10-17",
                        "Statement": [{
                            "Action": ["logs:*"],
                            "Resource": "arn:aws:logs:*:*:*",
                            "Effect": "Allow"
                        }]
                    })],
                AssumeRolePolicyDocument={
                    "Version": "2012-10-17",
                    "Statement": [{
                        "Action": ["sts:AssumeRole"],
                        "Effect": "Allow",
                        "Principal": {
                            "Service": ["lambda.amazonaws.com"]
                        }
                    }]
                },
            )
        )


def main():
    template_factory = BackendTemplateFactory()

    template = template_factory.create_template()

    print(template.to_yaml())


if __name__ == "__main__":
    main()
