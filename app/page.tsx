import { ClawCompanyApp } from "../components/ClawCompanyApp";
import { AuthGate } from "../components/AuthGate";
export default function Page(){return <AuthGate><ClawCompanyApp/></AuthGate>;}
